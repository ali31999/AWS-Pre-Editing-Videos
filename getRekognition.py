import json
import boto3
import urllib.parse
import urllib.request
import urllib.error
import os
import xml.etree.ElementTree as ET
from xml.dom import minidom

# Initialize AWS SDK clients
rekognition_client = boto3.client('rekognition')
s3_client = boto3.client('s3')

# --- Notion, S3 & Google Apps Script Configuration ---
NOTION_SECRET = os.environ.get('NOTION_TOKEN', 'YOUR_NOTION_TOKEN')
DIRECTORY_DB_ID = os.environ.get('DIRECTORY_DATABASE_ID', '288ad09a-c911-81de-8ec8-000bb1bf0552')
OUTPUT_BUCKET = os.environ.get('OUTPUT_BUCKET', 'cosmic-data-ocean')
GAS_XML_WEBHOOK_URL = os.environ.get('GAS_XML_WEBHOOK_URL', '')
ENABLE_S3_BACKUP = os.environ.get('ENABLE_S3_BACKUP', 'false').lower() == 'true'

# --- Option 1: Fixed Local Ingest Directory on PC ---
# Standard editing directory where unzipped video clips & XML sit locally (e.g. C:/VIDEO EDIT)
LOCAL_INGEST_PATH = os.environ.get('LOCAL_INGEST_PATH', 'C:/VIDEO EDIT')
INCLUDE_SUBFOLDER_IN_PATH = os.environ.get('INCLUDE_SUBFOLDER_IN_PATH', 'false').lower() == 'true'

# --- Creative Media Tag Taxonomy Mapping Table ---
TAXONOMY_MAP = {
    "skateboard": "SKATEBOARDING",
    "skateboarding": "SKATEBOARDING",
    "skater": "SKATEBOARDING",
    "sports": "SKATEBOARDING",
    "action": "SKATEBOARDING",
    "performing arts": "MUSIC",
    "musician": "MUSIC",
    "concert": "MUSIC",
    "singing": "MUSIC",
    "musical instrument": "MUSIC",
    "crowd": "EVENTS",
    "stage": "EVENTS",
    "audience": "EVENTS",
    "clothing": "CORE LOGO",
    "apparel": "CORE LOGO",
    "t-shirt": "CORE LOGO",
    "shirt": "CORE LOGO",
    "sleeve": "CORE LOGO",
    "top": "CORE LOGO",
    "beanie": "BEANIE",
    "hat": "TRUCKER HAT",
    "cap": "TRUCKER HAT",
    "baseball cap": "TRUCKER HAT",
    "pants": "VANDALISM PANTS",
    "jeans": "VANDALISM PANTS",
    "trousers": "VANDALISM PANTS",
    "sweatpants": "VANDALISM PANTS",
    "hoodie": "VANDALISM ZIP UP HOODIE",
    "jacket": "VANDALISM ZIP UP HOODIE",
    "sweater": "VANDALISM ZIP UP HOODIE",
    "behind the scenes": "BEHIND THE SCENES"
}

# --- Premiere Color Label Mapping (Rose, Forest, Cerulean, Violet, Mango) ---
COLOR_LABEL_MAP = {
    'SKATEBOARDING': 'Rose',       # Pink/Rose for Skate & Action
    'MUSIC': 'Forest',             # Green for Dialogue & Music
    'EVENTS': 'Forest',            # Green for Live Shows & Crowd
    'CORE LOGO': 'Cerulean',       # Blue for Apparel Products
    'BEANIE': 'Cerulean',
    'TRUCKER HAT': 'Cerulean',
    'VANDALISM PANTS': 'Cerulean',
    'VANDALISM ZIP UP HOODIE': 'Cerulean',
    'BEHIND THE SCENES': 'Violet', # Purple/Violet for BTS & Production
    'RAW': 'Mango'                 # Distinct Mango/Orange for unclassified B-Roll
}

def lambda_handler(event, context):
    """
    Sovereign Lambda 2 (v16.0 GD Parent ID Hierarchy & Zero-Click Auto-Link Edition):
    1. Parses Rekognition SNS completion event for video.
    2. Retrieves video labels AND native video duration metadata from Rekognition.
    3. Finds the parent folder in Notion to extract its Google Drive Folder ID.
    4. Queries Notion by 'GD Parent ID' to fetch all video pages under that folder,
       eliminating title mismatch and apostrophe encoding bugs for sibling clips.
    5. Tags Notion DB with AI taxonomy for active file and all folder sibling clips.
    6. Aggregates all folder clips into a 100% compliant Final Cut Pro 7 / Premiere XML.
    7. Formats pathurl with exact absolute Windows URI (e.g. file://localhost/C%3a/VIDEO%20EDIT/filename.mp4)
       matching Adobe Premiere Pro's native locator schema for 100% instant auto-link!
    8. Uses actual video duration (in frames) instead of a hardcoded 10-second default.
    9. Applies distinct Premiere color labels (Rose, Forest, Cerulean, Violet, Mango).
    10. Dispatches Master Timeline XML directly to Google Drive parent folder via GAS webhook.
    """
    print("Received SNS Event:", json.dumps(event))
    
    # 1. Parse SNS Message content
    records = event.get('Records', [])
    if not records:
        print("[WARN] No Records found in event.")
        return {"statusCode": 400, "body": "No records in event."}
        
    sns_raw = records[0].get('Sns', {}).get('Message')
    if not sns_raw:
        print("[WARN] No SNS message found.")
        return {"statusCode": 400, "body": "No SNS message."}
        
    sns_message = json.loads(sns_raw) if isinstance(sns_raw, str) else sns_raw
    job_id = sns_message.get('JobId')
    status = sns_message.get('Status')
    
    print(f"Rekognition Job ID: {job_id} | Status: {status}")
    
    if status != 'SUCCEEDED':
        print(f"Rekognition Job Failed or Aborted ({status}). Aborting Notion Update.")
        return {"statusCode": 400, "body": f"Job status: {status}"}
        
    # 2. Extract S3 Bucket, Key & Inferred Folder/File names
    video_meta = sns_message.get('Video', {})
    s3_bucket = video_meta.get('S3Bucket') or OUTPUT_BUCKET
    raw_s3_key = video_meta.get('S3ObjectName', '')
    s3_key = urllib.parse.unquote_plus(raw_s3_key)
    print(f"Analyzing completed file: '{s3_key}' in bucket: '{s3_bucket}'")
    
    path_parts = s3_key.split('/')
    if len(path_parts) > 1:
        folder_prefix = s3_key.rsplit('/', 1)[0] + '/'
        folder_name = path_parts[-2]
        file_name = path_parts[-1]
    else:
        folder_prefix = ""
        folder_name = "Raw_Clips"
        file_name = s3_key
        
    print(f"Parent Folder: '{folder_name}' (Prefix: '{folder_prefix}') | Active File: '{file_name}'")
    
    # 3. Retrieve Label Detection Results AND Native Video Duration Metadata from Rekognition
    rekog_data = get_rekognition_labels_and_metadata(job_id)
    labels = rekog_data.get('labels', [])
    detected_duration_ms = rekog_data.get('duration_millis')
    print(f"Retrieved {len(labels)} labels from Rekognition. Detected Duration: {detected_duration_ms} ms")
    
    # 4. Map Rekognition labels to Creative Media Tag Taxonomy (Confidence >= 70%)
    matched_tags = set()
    for item in labels:
        label_name = item.get('Label', {}).get('Name', '').lower()
        confidence = item.get('Label', {}).get('Confidence', 0.0)
        
        if confidence >= 70.0 and label_name in TAXONOMY_MAP:
            matched_tags.add(TAXONOMY_MAP[label_name])
                
    tags_list = [t for t in matched_tags if t != "RAW"]
    print(f"Matched Taxonomy Tags (Confidence >= 70%): {tags_list}")
    
    # 5. S3 Folder Aggregation: Discover all video clips in the same folder
    folder_video_files = list_folder_videos(s3_bucket, folder_prefix, file_name)
    print(f"[AGGREGATION] Found {len(folder_video_files)} video clips in '{folder_name}': {folder_video_files}")

    # 6. Retrieve Folder G-Drive ID and Query Notion by 'GD Parent ID'
    folder_page_id, folder_gdrive_id = find_folder_gdrive_id(folder_name)
    print(f"[NOTION FOLDER] Page ID: {folder_page_id} | G-Drive Folder ID: {folder_gdrive_id}")

    # Fetch all Notion pages that share this parent folder G-Drive ID
    child_pages = find_pages_by_parent_gdrive_id(folder_gdrive_id) if folder_gdrive_id else []

    # Resolve active file page
    page_id, file_gdrive_id = resolve_file_page(folder_name, file_name, child_pages)
    gdrive_id = folder_gdrive_id or file_gdrive_id

    # Update active file page in Notion
    if page_id:
        success = update_notion_multi_select(page_id, tags_list)
        if success:
            print(f"Notion Page '{page_id}' for '{file_name}' successfully updated with tags: {tags_list}")
        else:
            print(f"Failed updating Notion Page '{page_id}' properties.")
    else:
        print(f"[WARN] No matching file page for '{file_name}' found in Drive Directory DB. Folder page was NOT overwritten.")

    # Tag sibling files in folder ONLY if they currently have NO theme tags in Notion
    for sibling_file in folder_video_files:
        if sibling_file != file_name:
            sib_page_id, _ = resolve_file_page(folder_name, sibling_file, child_pages)
            if sib_page_id:
                # Check if sibling page already has tags in Notion so we NEVER clobber existing tags!
                has_existing_tags = False
                if child_pages:
                    for cp in child_pages:
                        if cp.get('id') == sib_page_id:
                            existing_multi = cp.get('properties', {}).get('Theme', {}).get('multi_select', [])
                            if existing_multi:
                                has_existing_tags = True
                                existing_names = [t.get('name') for t in existing_multi]
                                print(f"[SIBLING NOTION SKIP] '{sibling_file}' already has tags {existing_names}. Preserving.")
                            break
                if not has_existing_tags:
                    sib_tags = infer_tags_from_filename(sibling_file)
                    if sib_tags:
                        update_notion_multi_select(sib_page_id, sib_tags, merge=False)
                        print(f"[SIBLING NOTION SYNC] Inferred tags for '{sibling_file}' (Page {sib_page_id}): {sib_tags}")
                    else:
                        print(f"[SIBLING NOTION SKIP] No filename tags inferred for '{sibling_file}'. Leaving for its own Rekognition run.")
            else:
                print(f"[SIBLING SKIP] No dedicated Notion page found for sibling '{sibling_file}'. Folder page protected.")

    # 7. Compile Multi-Clip Premiere XML Timeline (v16.0 Option 1 Zero-Click Auto-Link)
    xml_content = build_premiere_multiclip_xml(
        folder_name=folder_name,
        clip_files=folder_video_files,
        active_file=file_name,
        active_tags=tags_list,
        active_duration_ms=detected_duration_ms,
        local_base_dir=LOCAL_INGEST_PATH,
        include_subfolder=INCLUDE_SUBFOLDER_IN_PATH
    )
    clean_folder = folder_name.replace(' ', '_')
    xml_filename = f"{clean_folder}_Master_Timeline.xml"

    # 8. Dispatch XML to Google Drive via GAS Webhook
    gdrive_upload_result = None
    if gdrive_id and GAS_XML_WEBHOOK_URL:
        print(f"[G-DRIVE DISPATCH] Found G-Drive ID '{gdrive_id}'. Sending XML via Google Apps Script...")
        gdrive_upload_result = dispatch_xml_to_gdrive(GAS_XML_WEBHOOK_URL, gdrive_id, xml_filename, xml_content)
        print(f"[G-DRIVE RESULT] {gdrive_upload_result}")
    else:
        print(f"[G-DRIVE SKIP] G-Drive ID ({gdrive_id}) or GAS_XML_WEBHOOK_URL missing. Skipping Google Drive direct upload.")

    # 9. Optional Backup XML to S3 Bucket
    xml_s3_key = None
    if ENABLE_S3_BACKUP:
        xml_s3_key = f"xml/{xml_filename}"
        try:
            s3_client.put_object(
                Bucket=OUTPUT_BUCKET,
                Key=xml_s3_key,
                Body=xml_content.encode('utf-8'),
                ContentType='application/xml'
            )
            print(f"[S3 BACKUP] Saved timeline sequence to s3://{OUTPUT_BUCKET}/{xml_s3_key}")
        except Exception as e:
            print(f"[S3 BACKUP WARN] Could not save copy to S3: {e}")
    else:
        print("[S3 BACKUP] S3 backup disabled to prevent re-triggering scanVideoRekognition.")

    return {
        "statusCode": 200,
        "body": json.dumps({
            "status": "SUCCESS",
            "folder": folder_name,
            "clips_aggregated": folder_video_files,
            "active_file": file_name,
            "tags": tags_list,
            "notion_page_id": page_id,
            "gdrive_folder_id": gdrive_id,
            "gdrive_upload": gdrive_upload_result,
            "xml_s3_key": xml_s3_key
        })
    }

def get_rekognition_labels_and_metadata(job_id):
    """Retrieves all completed Rekognition job results AND video duration metadata."""
    results = []
    duration_millis = None
    response = rekognition_client.get_label_detection(JobId=job_id, MaxResults=100)
    results.extend(response.get('Labels', []))
    
    video_meta = response.get('VideoMetadata', {})
    if 'DurationMillis' in video_meta:
        duration_millis = video_meta['DurationMillis']
        
    next_token = response.get('NextToken')
    while next_token:
        response = rekognition_client.get_label_detection(JobId=job_id, MaxResults=100, NextToken=next_token)
        results.extend(response.get('Labels', []))
        if not duration_millis and 'DurationMillis' in response.get('VideoMetadata', {}):
            duration_millis = response['VideoMetadata']['DurationMillis']
        next_token = response.get('NextToken')
        
    return {
        'labels': results,
        'duration_millis': duration_millis
    }

def list_folder_videos(bucket, folder_prefix, fallback_file):
    """Lists all supported video files in the specified S3 folder prefix."""
    videos = []
    if folder_prefix:
        try:
            resp = s3_client.list_objects_v2(Bucket=bucket, Prefix=folder_prefix, Delimiter='/')
            for item in resp.get('Contents', []):
                key = item['Key']
                fname = key.split('/')[-1]
                if fname and fname.lower().endswith(('.mp4', '.mov', '.m4v')):
                    videos.append(fname)
        except Exception as e:
            print(f"[S3 LIST WARN] Could not list folder objects: {e}")
            
    if fallback_file not in videos:
        videos.append(fallback_file)
        
    videos.sort()
    return videos

def notion_request(url, method, payload=None):
    """Executes authenticated Notion API calls using standard library urllib.request."""
    headers = {
        "Authorization": f"Bearer {NOTION_SECRET}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json"
    }
    data = json.dumps(payload).encode('utf-8') if payload else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            body = resp.read().decode('utf-8')
            return resp.getcode(), json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        err_body = e.read().decode('utf-8')
        print(f"[NOTION HTTP ERROR] {e.code}: {err_body}")
        return e.code, {}
    except Exception as e:
        print(f"[NOTION REQUEST ERROR] {e}")
        return 500, {}

def normalize_stem(text):
    """Strips file extensions, apostrophes (straight and curly), quotes, and punctuation."""
    if not text:
        return ""
    stem = text.rsplit('.', 1)[0] if '.' in text else text
    cleaned = stem.lower()
    for ch in ["'", "’", "`", '"', "“", "”"]:
        cleaned = cleaned.replace(ch, "")
    for ch in ["_", "-", "."]:
        cleaned = cleaned.replace(ch, " ")
    return " ".join(cleaned.split())

def find_pages_by_parent_gdrive_id(parent_gdrive_id):
    """
    Retrieves all Notion pages registered under this Google Drive folder
    by querying the 'GD Parent ID' property.
    """
    if not parent_gdrive_id:
        return []
    url = f"https://api.notion.com/v1/databases/{DIRECTORY_DB_ID}/query"
    for prop in ["GD Parent ID", "G-Parent ID", "Parent ID", "GDrive Parent ID"]:
        payload = {
            "filter": {
                "property": prop,
                "rich_text": {"equals": parent_gdrive_id}
            }
        }
        status, data = notion_request(url, "POST", payload)
        if status == 200 and data.get("results"):
            print(f"[NOTION QUERY] Found {len(data['results'])} child pages with '{prop}' = '{parent_gdrive_id}'")
            return data["results"]
    return []

def resolve_file_page(folder_name, file_name, child_pages=None):
    """
    Resolves the dedicated Notion page for a video file:
    Step 1: Matches against child pages belonging to the same GD Parent ID.
    Step 2: If unlinked or not found, falls back to multi-candidate database search.
    Guards against returning the parent folder page as the file page.
    Returns: (page_id, gdrive_id)
    """
    clean_target = normalize_stem(file_name)
    target_tokens = [w for w in clean_target.split() if len(w) >= 3]

    # Step 1: Match within child pages belonging to GD Parent ID
    if child_pages:
        # Pass 1A: Exact normalized stem match
        for page in child_pages:
            props = page.get('properties', {})
            title_prop = props.get('Title', {}).get('title', [])
            page_title = title_prop[0]['text']['content'] if title_prop else ''
            clean_page_title = normalize_stem(page_title)

            # Reject parent folder row
            if clean_page_title == normalize_stem(folder_name):
                continue

            if clean_target == clean_page_title:
                page_id = page['id']
                gdrive_id = extract_gdrive_id(page)
                print(f"[NOTION RESOLVED VIA GD PARENT ID] Exact: '{file_name}' matched page '{page_title}' (ID: {page_id})")
                return page_id, gdrive_id

        # Pass 1B: Token containment match
        for page in child_pages:
            props = page.get('properties', {})
            title_prop = props.get('Title', {}).get('title', [])
            page_title = title_prop[0]['text']['content'] if title_prop else ''
            clean_page_title = normalize_stem(page_title)

            if clean_page_title == normalize_stem(folder_name):
                continue

            if target_tokens and all(tok in clean_page_title for tok in target_tokens):
                page_id = page['id']
                gdrive_id = extract_gdrive_id(page)
                print(f"[NOTION RESOLVED VIA GD PARENT ID] Token Match: '{file_name}' matched page '{page_title}' (ID: {page_id})")
                return page_id, gdrive_id

    # Step 2: Fallback query directly across Notion DB
    url = f"https://api.notion.com/v1/databases/{DIRECTORY_DB_ID}/query"
    clean_stem = file_name.rsplit('.', 1)[0]
    stem_straight = clean_stem.replace('’', "'")
    stem_curly = clean_stem.replace("'", '’')
    stem_no_punct = clean_stem.replace("'", "").replace('’', "").strip()

    search_candidates = list(dict.fromkeys([
        file_name,
        clean_stem,
        stem_straight,
        stem_curly,
        stem_no_punct
    ]))

    or_filters = [{"property": "Title", "title": {"equals": c}} for c in search_candidates]
    or_filters.extend([{"property": "Title", "title": {"contains": c}} for c in [clean_stem, stem_no_punct] if len(c) >= 3])

    payload = {"filter": {"or": or_filters}}
    status, data = notion_request(url, "POST", payload)
    
    if status == 200 and data.get('results'):
        for page in data['results']:
            props = page.get('properties', {})
            title_prop = props.get('Title', {}).get('title', [])
            page_title = title_prop[0]['text']['content'] if title_prop else ''
            
            if page_title.strip().lower() == folder_name.strip().lower():
                continue
                
            page_id = page['id']
            gdrive_id = extract_gdrive_id(page)
            print(f"[NOTION RESOLVED VIA FALLBACK] Exact Match: '{file_name}' (Title: '{page_title}') -> ID: {page_id}")
            return page_id, gdrive_id

    print(f"[NOTION NOT FOUND] No dedicated file page match for '{file_name}'.")
    return None, None

def find_folder_gdrive_id(folder_name):
    """
    Searches Notion for the parent folder row to extract its G-Drive ID for XML dispatch.
    Never assigns this page ID as a file's page ID.
    Returns: (folder_page_id, folder_gdrive_id) or (None, None)
    """
    url = f"https://api.notion.com/v1/databases/{DIRECTORY_DB_ID}/query"
    payload = {
        "filter": {
            "property": "Title",
            "title": {"contains": folder_name}
        }
    }
    status, data = notion_request(url, "POST", payload)
    if status == 200 and data.get('results'):
        for page in data['results']:
            props = page.get('properties', {})
            title_prop = props.get('Title', {}).get('title', [])
            page_title = title_prop[0]['text']['content'] if title_prop else ''
            
            if folder_name.lower() in page_title.lower():
                page_id = page['id']
                gdrive_id = extract_gdrive_id(page)
                print(f"[NOTION RESOLVED] Folder Page Match: '{page_title}' -> ID: {page_id} | G-Drive ID: {gdrive_id}")
                return page_id, gdrive_id
                
        first = data['results'][0]
        return first['id'], extract_gdrive_id(first)
        
    return None, None

def extract_gdrive_id(page_obj):
    """Extracts G-Drive ID string from Notion page properties."""
    props = page_obj.get('properties', {})
    for prop_key in ["G-Drive ID", "G-DRIVE ID", "GDrive ID", "GD Parent ID"]:
        if prop_key in props:
            val_obj = props[prop_key]
            if val_obj.get('type') == 'rich_text' and val_obj.get('rich_text'):
                return val_obj['rich_text'][0]['plain_text']
    return None

def update_notion_multi_select(page_id, tags, merge=False):
    """
    Updates Notion Drive Directory multi-select property 'Theme'.
    merge=False (Default): Overwrites with strictly newly detected tags.
    Eliminates zombie/leftover tags from past broken runs!
    """
    url = f"https://api.notion.com/v1/pages/{page_id}"
    
    if merge:
        status, page_data = notion_request(url, "GET")
        existing_tags = []
        if status == 200:
            props = page_data.get('properties', {})
            if 'Theme' in props and props['Theme'].get('multi_select'):
                existing_tags = [t['name'] for t in props['Theme']['multi_select']]
        final_tags = list(set(existing_tags + tags))
    else:
        # Strictly preserve order while deduplicating
        final_tags = list(dict.fromkeys(tags))
        
    multi_select_values = [{"name": tag} for tag in final_tags]
    
    payload = {
        "properties": {
            "Theme": {
                "multi_select": multi_select_values
            },
            "Notes": {
                "rich_text": [{"text": {"content": "Auto-analyzed via AWS Rekognition Lambda (v16.0 Clean Tagging)"}}]
            }
        }
    }
    patch_status, _ = notion_request(url, "PATCH", payload)
    return patch_status == 200

def infer_tags_from_filename(filename):
    """
    Infers taxonomy tags strictly from filename keywords.
    Never falls back to copying another video's tags!
    """
    lower = filename.lower()
    inferred = set()
    
    # Matches 'skate', 'skating', 'skater', 'skateboard', 'ollie', etc.
    if any(k in lower for k in ['skat', 'trick', 'rail', 'park', 'kickflip', 'heelflip', 'venice', 'ollie', 'grind']):
        inferred.add("SKATEBOARDING")
    if any(k in lower for k in ['music', 'concert', 'interview', 'talk', 'dialog', 'audio', 'vocal', 'song', 'album']):
        inferred.add("MUSIC")
    if any(k in lower for k in ['hat', 'beanie', 'cap']):
        inferred.add("TRUCKER HAT")
    if any(k in lower for k in ['pant', 'jean', 'trouser', 'sweatpant']):
        inferred.add("VANDALISM PANTS")
    if any(k in lower for k in ['hoodie', 'jacket', 'sweater']):
        inferred.add("VANDALISM ZIP UP HOODIE")
    if any(k in lower for k in ['shirt', 'apparel', 'clothing', 'logo', 'tee']):
        inferred.add("CORE LOGO")
    if any(k in lower for k in ['bts', 'setup', 'screenprint']):
        inferred.add("BEHIND THE SCENES")
        
    return [t for t in list(inferred) if t != "RAW"]

def dispatch_xml_to_gdrive(webhook_url, folder_id, file_name, xml_content):
    """Sends compiled XML payload to Google Apps Script Webhook to write into Google Drive."""
    payload = {
        "folderId": folder_id,
        "fileName": file_name,
        "xmlContent": xml_content
    }
    data = json.dumps(payload).encode('utf-8')
    headers = {"Content-Type": "application/json"}
    req = urllib.request.Request(webhook_url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req) as resp:
            res_body = resp.read().decode('utf-8')
            return json.loads(res_body) if res_body else {"status": "SUCCESS", "code": resp.getcode()}
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode('utf-8')
        print(f"[GAS WEBHOOK HTTP ERROR] {e.code}: {err_msg}")
        return {"status": "ERROR", "code": e.code, "detail": err_msg}
    except Exception as e:
        print(f"[GAS WEBHOOK EXCEPTION] {e}")
        return {"status": "ERROR", "detail": str(e)}

def get_color_for_clip(clip_name, active_file, active_tags):
    """Determines clip label color for Adobe Premiere Pro based on taxonomy tags."""
    lower = clip_name.lower()
    if clip_name == active_file and active_tags:
        for tag in active_tags:
            if tag in COLOR_LABEL_MAP:
                return COLOR_LABEL_MAP[tag]
                
    if any(k in lower for k in ['skat', 'skate', 'trick', 'rail', 'park', 'kickflip', 'heelflip', 'venice']):
        return 'Rose'
    elif any(k in lower for k in ['music', 'concert', 'interview', 'talk', 'dialog', 'audio', 'vocal']):
        return 'Forest'
    elif any(k in lower for k in ['hat', 'beanie', 'pants', 'hoodie', 'product']):
        return 'Cerulean'
    elif any(k in lower for k in ['bts', 'setup', 'screenprint', 'shipping', 'studio']):
        return 'Violet'
    elif any(k in lower for k in ['slow', '120fps', 'broll', 'img', 'raw']):
        return 'Mango'
        
    if active_tags:
        for tag in active_tags:
            if tag in COLOR_LABEL_MAP:
                return COLOR_LABEL_MAP[tag]
    return 'Mango'

def format_premiere_pathurl(base_dir, clip_name, folder_name=None, include_subfolder=False):
    """
    Constructs an absolute file://localhost/ URI matching Adobe Premiere Pro's Windows path encoding.
    Example output:
      file://localhost/C%3a/VIDEO%20EDIT/1Recording%202026-06-23%20175832.mp4
    """
    clean_base = base_dir.replace('\\', '/').rstrip('/')
    if include_subfolder and folder_name:
        clean_base = f"{clean_base}/{folder_name.strip()}"
        
    if len(clean_base) >= 2 and clean_base[1] == ':':
        drive = clean_base[0].upper() + '%3a'
        rest = clean_base[2:].lstrip('/')
        encoded_parts = [urllib.parse.quote(part) for part in rest.split('/') if part]
        encoded_rest = '/' + '/'.join(encoded_parts) if encoded_parts else ''
        full_dir = drive + encoded_rest
    else:
        encoded_parts = [urllib.parse.quote(part) for part in clean_base.split('/') if part]
        full_dir = '/'.join(encoded_parts)
        
    encoded_file = urllib.parse.quote(clip_name)
    return f"file://localhost/{full_dir}/{encoded_file}"

def build_premiere_multiclip_xml(folder_name, clip_files, active_file, active_tags, active_duration_ms=None, local_base_dir='C:/VIDEO EDIT', include_subfolder=False, fps=24, fallback_duration_sec=15, gap_sec=1):
    """
    Constructs an Adobe Premiere Pro 100% compliant Final Cut Pro 7 XML timeline (v16.0 Option 1 Zero-Click Edition):
    1. Formats <pathurl> with exact absolute Windows URI scheme:
       file://localhost/C%3a/VIDEO%20EDIT/filename.mp4
       This matches Adobe Premiere Pro 2026's native file locator exactly so files in C:\\VIDEO EDIT link instantly!
    2. Calculates clip frames dynamically from Rekognition DurationMillis (or fallback).
    3. Assigns distinct color labels (Rose, Forest, Cerulean, Violet, Mango).
    4. Includes dual-stream video + audio samplecharacteristics so Premiere parses duration and sync properly.
    """
    gap_frames = gap_sec * fps
    clean_folder = folder_name.replace(' ', '_')
    
    clip_durations = {}
    for clip_name in clip_files:
        if clip_name == active_file and active_duration_ms:
            duration_sec = max(active_duration_ms / 1000.0, 1.0)
            frames = int(round(duration_sec * fps))
        else:
            frames = int(fallback_duration_sec * fps)
        clip_durations[clip_name] = frames
        
    total_duration = sum(clip_durations.values()) + (len(clip_files) * gap_frames)
    
    # 1. Root <xmeml> Element
    xmeml = ET.Element('xmeml', version='4')
    
    # 2. <sequence> Element
    sequence = ET.SubElement(xmeml, 'sequence', id='sequence-1')
    ET.SubElement(sequence, 'name').text = f"Cosmic_AI_{clean_folder}_Sequence"
    ET.SubElement(sequence, 'duration').text = str(total_duration)
    
    rate = ET.SubElement(sequence, 'rate')
    ET.SubElement(rate, 'timebase').text = str(fps)
    ET.SubElement(rate, 'ntsc').text = 'TRUE'
    
    # 3. <media> Block
    media = ET.SubElement(sequence, 'media')
    video = ET.SubElement(media, 'video')
    
    format_el = ET.SubElement(video, 'format')
    sc = ET.SubElement(format_el, 'samplecharacteristics')
    ET.SubElement(sc, 'width').text = '1920'
    ET.SubElement(sc, 'height').text = '1080'
    sc_rate = ET.SubElement(sc, 'rate')
    ET.SubElement(sc_rate, 'timebase').text = str(fps)
    ET.SubElement(sc_rate, 'ntsc').text = 'TRUE'
    
    # Video Track 1 (V1) containing all clips
    v_track = ET.SubElement(video, 'track')
    
    playhead = 0
    for idx, clip_name in enumerate(clip_files, 1):
        clean_stem = clip_name.rsplit('.', 1)[0].replace(' ', '_')
        color = get_color_for_clip(clip_name, active_file, active_tags)
        clip_frames = clip_durations[clip_name]
        
        start_frame = playhead
        end_frame = start_frame + clip_frames
        playhead = end_frame + gap_frames
        
        # --- Video Clipitem on V1 ---
        v_clip = ET.SubElement(v_track, 'clipitem', id=f"clipitem-{idx}")
        ET.SubElement(v_clip, 'name').text = clip_name
        ET.SubElement(v_clip, 'duration').text = str(clip_frames)
        
        v_c_rate = ET.SubElement(v_clip, 'rate')
        ET.SubElement(v_c_rate, 'timebase').text = str(fps)
        ET.SubElement(v_c_rate, 'ntsc').text = 'TRUE'
        
        ET.SubElement(v_clip, 'in').text = '0'
        ET.SubElement(v_clip, 'out').text = str(clip_frames)
        ET.SubElement(v_clip, 'start').text = str(start_frame)
        ET.SubElement(v_clip, 'end').text = str(end_frame)
        
        # Color Label (Rose, Forest, Cerulean, Violet, Mango)
        labels = ET.SubElement(v_clip, 'labels')
        ET.SubElement(labels, 'label2').text = color
        
        # File Source Descriptor with Option 1 Absolute Native URI
        file_el = ET.SubElement(v_clip, 'file', id=f"file-{clean_stem}")
        ET.SubElement(file_el, 'name').text = clip_name
        
        # Exact absolute pathurl matching Adobe Premiere Pro Windows locator schema
        path_url = format_premiere_pathurl(local_base_dir, clip_name, folder_name, include_subfolder)
        ET.SubElement(file_el, 'pathurl').text = path_url
        
        f_rate = ET.SubElement(file_el, 'rate')
        ET.SubElement(f_rate, 'timebase').text = str(fps)
        ET.SubElement(f_rate, 'ntsc').text = 'TRUE'
        ET.SubElement(file_el, 'duration').text = str(clip_frames)
        
        # Embedded Media Characteristics (Video + Audio)
        f_media = ET.SubElement(file_el, 'media')
        f_vid = ET.SubElement(f_media, 'video')
        f_vid_sc = ET.SubElement(f_vid, 'samplecharacteristics')
        ET.SubElement(f_vid_sc, 'width').text = '1920'
        ET.SubElement(f_vid_sc, 'height').text = '1080'
        
        f_aud = ET.SubElement(f_media, 'audio')
        f_aud_sc = ET.SubElement(f_aud, 'samplecharacteristics')
        ET.SubElement(f_aud_sc, 'depth').text = '16'
        ET.SubElement(f_aud_sc, 'samplerate').text = '48000'
        ET.SubElement(f_aud_sc, 'channelcount').text = '2'

    raw_xml = ET.tostring(xmeml, encoding='utf-8')
    parsed_xml = minidom.parseString(raw_xml)
    return parsed_xml.toprettyxml(indent='  ')
