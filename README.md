# AWS-Pre-Editing-Videos
S3 Bucket -> Lambda: Start Rekognition  -> Rekognition  -> SNS Topic -> Lambda: Process Results  -> Notion

<img width="1812" height="1973" alt="Cosmic System — AWS Rekognition to Premiere Pro" src="https://github.com/user-attachments/assets/19d3cfc5-91e7-4729-84cf-61be1a5f3ce8" />

### The Problem
Video editors spend **2–4 hours per shoot** manually ingesting, organizing, tagging, and assembling raw footage into rough draft timelines before creative editing can begin.

### The Solution
An enterprise-grade, **event-driven serverless cloud pipeline** that automates the entire pre-editing workflow:
1. **Detects & Analyzes:** Computer vision detects actions and apparel objects while extracting true video runtimes.
2. **Tags & Catalogs:** Syncs metadata to Notion with folder-level parent-child isolation.
3. **Generates Sequence:** Dynamically compiles a **Final Cut Pro 7 XML timeline** formatted with native Windows file URIs (`C:\VIDEO EDIT\`).

### The Business Impact
* **95% Reduction in Pre-Editing Time:** Drops manual footage sorting from ~120 minutes to under 30 seconds.
* **Zero-Click NLE Linkage:** Importing the `.xml` into Adobe Premiere Pro opens the timeline with **100% online, linked media, true durations, and color taxonomy bins**—with no manual linking dialogs.

---

## Architecture Data Flow

```text
 [ Producer Upload ] ──► [ Amazon S3: "cosmic-data-ocean" ]
                               │ (ObjectCreated:Put Event)
                               ▼
                    [ Lambda 1: "scanVideoRekognition" ]
                               │ (StartLabelDetection @ MinConfidence=70)
                               ▼
                    [ Amazon Rekognition Video Engine ]
                               │ (Asynchronous Completion Event)
                               ▼
                    [ Amazon SNS Topic: "SNSRekognitionVideoEdit" ]
                               │
               ┌───────────────┴───────────────┐
               ▼                               ▼
 [ Amazon CloudWatch Alarms ]     [ Lambda 2: "getRekognition" (v16.0) ]
   (Errors >= 1 ──► Email Alert)   ├── Extracts DurationMillis & True FPS
                                   ├── Isolates DB Rows via "GD Parent ID"
                                   ├── Applies Clean AI Taxonomy (Skate, Music)
                                   └── Compiles FCP7 Premiere XML Timeline
                                               │
                                               ▼ (HTTP POST Webhook)
                                 [ Google Apps Script: "XML_Drive_Writer.gs" ]
                                               │
                                               ▼
                                 [ Google Drive Folder / Local PC ]
                                 Path: C:\VIDEO EDIT\
                                               │
                                               ▼ (Import Sequence)
                                 [ Adobe Premiere Pro 2026 ]
                                 ✅ 100% Online Media (Track V1)
                                 ✅ Accurate Video Durations
                                 ✅ Custom Color Label Bins
```

---

## Tech Stack & Engineering Decisions

| Layer | Service / Tool | Why Chosen Over Alternative |
| :--- | :--- | :--- |
| **Ingestion** | **Amazon S3** (`cosmic-data-ocean`) | Event-driven bucket notifications at near-zero idle cost vs. Amazon EFS (which requires active VPC mount targets). |
| **Compute** | **AWS Lambda** (Python 3.12) | Serverless micro-billing (scales to zero) vs. continuous EC2 instances. |
| **Vision AI** | **Amazon Rekognition Video** | Managed asynchronous action and label detection vs. hosting custom PyTorch/YOLO inference models on GPU instances (\$1.00+/hr). |
| **Pub/Sub** | **Amazon SNS** | Native push architecture with instant trigger execution vs. polling loops with SQS. |
| **Relational Metadata** | **Notion Database API** | Cloud-native CMS for team collaboration; queried via `GD Parent ID` for folder isolation. |
| **Timeline Engine** | **Final Cut Pro 7 XML (`xmeml v4`)** | Supported natively across Adobe Premiere Pro and DaVinci Resolve; avoids binary proprietary `.prproj` formats. |

---

## Color Taxonomy Mapping Matrix

Clips are color-coded in Premiere Pro based on detected objects and activities:

| Taxonomy Tag | Detection Triggers | Premiere Label Color | Target Editing Track |
| :--- | :--- | :--- | :--- |
| **`SKATEBOARDING`** | Skate, Action, Trick, Ollie, Grind | **Rose** (Pink) | Action / B-Roll Sequence |
| **`MUSIC`** | Concert, Vocal, Instrument, Stage | **Forest** (Green) | Dialogue / A-Roll Sync |
| **`CORE LOGO` / Merch** | Apparel, Hoodie, Beanie, Pants | **Cerulean** (Blue) | Product Placement Cutaways |
| **`BEHIND THE SCENES`** | Studio, Screenprinting, Setup | **Violet** (Purple) | Documentary Lore / Vlogs |
| **`B-ROLL`** | Unclassified / Secondary Footage | **Mango** (Orange) | Cutaways & Overlays |

---

## Quickstart: How to Use the System

### 1. Ingest Video Media
Drop video clips (`.mp4`, `.mov`) into your cloud folder or directly into Amazon S3:
```bash
aws s3 cp my-clip.mp4 s3://cosmic-data-ocean/AWS\ Rekognition\ TEST/
```

### 2. Automated Cloud Pipeline Execution
1. S3 triggers `scanVideoRekognition`, starting a label detection job.
2. Upon completion, Amazon SNS alerts `getRekognition` (v16.0).
3. The function logs tags to Notion and exports `AWS_Rekognition_TEST_Master_Timeline.xml` back to Google Drive via Google Apps Script.

### 3. One-Click Editing in Adobe Premiere Pro
1. Move your downloaded clips and `.xml` into your local directory:
   ```text
   C:\VIDEO EDIT\
   ```
2. Open **Adobe Premiere Pro** \\(\rightarrow\\) **File** \\(\rightarrow\\) **Import** \\(\rightarrow\\) Select the `.xml` file.
3. **Result:** The timeline sequence loads onto **Track V1** with all media online, accurate durations, and color-coded bins—ready for narrative assembly.

---

## Enterprise Security & Well-Architected Standards

* **Least-Privilege IAM Roles:** Stateless execution roles with scoped resource ARNs (`s3:GetObject`, `rekognition:*`, `sns:Publish`); zero hardcoded AWS access keys.
* **Encrypted Secrets:** External tokens (`NOTION_TOKEN`, Google Apps Script webhooks) are managed strictly via environment variables.
* **Storage Lifecycle Rules:** Automated lifecycle transitions move raw footage to **S3 Glacier Flexible Retrieval** after 30 days and expire temporary XMLs after 7 days, cutting recurring storage costs by **>80%**.
* **Observability & Alerting:** Configured CloudWatch metric alarms trigger SNS email alerts on any Lambda execution errors (`Errors >= 1`).

---

## Author & Contact
* **Engineer:** Ali Bilal
* **Project:** Final Project: AWS Architecture Portfolio Project (*Machine Learning on AWS*)
* **Email:** ali.cosmicdemise@gmail.com
