import json
import boto3
import os
import urllib.parse

rekognition_client = boto3.client('rekognition')

# Defaults for account 054892330377 — override via Lambda environment variables if needed.
DEFAULT_SNS_TOPIC_ARN = 'arn:aws:sns:us-east-1:054892330377:SNSRekognitionVideoEdit'


def lambda_handler(event, context):
    """
    Lambda 1: S3 trigger -> start Rekognition video label detection.

    Required Lambda environment variables:
      - REKOGNITION_ROLE_ARN  IAM role Rekognition assumes to publish to SNS
                              (must trust rekognition.amazonaws.com, NOT the Lambda role)
      - SNS_TOPIC_ARN         (optional) defaults to your SNSRekognitionVideoEdit topic

    Optional:
      - MIN_CONFIDENCE        default 75
    """
    print("Received event: " + json.dumps(event))

    file_name = 'Unknown'

    try:
        records = event.get('Records', [])
        if not records:
            print("[WARN] No Records found in event.")
            return {'statusCode': 400, 'body': 'No S3 records found.'}

        bucket_name = records[0]['s3']['bucket']['name']
        raw_file_name = records[0]['s3']['object']['key']
        file_name = urllib.parse.unquote_plus(raw_file_name)
        print(f"[INGEST] New file detected: '{file_name}' inside bucket: '{bucket_name}'")

        lower_name = file_name.lower()
        if not (lower_name.endswith('.mp4') or lower_name.endswith('.mov') or lower_name.endswith('.m4v')):
            print(f"[SKIP] File '{file_name}' is not a supported video format.")
            return {
                'statusCode': 200,
                'body': json.dumps(
                    f"File {file_name} skipped. Only .mp4, .mov, and .m4v are analyzed."
                ),
            }

        sns_topic_arn = os.environ.get('SNS_TOPIC_ARN', DEFAULT_SNS_TOPIC_ARN)
        role_arn = os.environ.get('REKOGNITION_ROLE_ARN', '').strip()
        min_confidence = int(os.environ.get('MIN_CONFIDENCE', '75'))

        if not role_arn:
            msg = (
                "Missing REKOGNITION_ROLE_ARN environment variable. "
                "Create an IAM role that trusts rekognition.amazonaws.com and allows "
                "sns:Publish to your SNS topic, then paste its ARN here."
            )
            print(f"[ERROR] {msg}")
            return {'statusCode': 500, 'body': json.dumps(msg)}

        print(f"[REKOGNITION] Starting label detection for: {file_name}")
        print(
            f"[CONFIG] SNS Topic: {sns_topic_arn} | Role: {role_arn} | "
            f"Confidence Threshold: {min_confidence}%"
        )

        response = rekognition_client.start_label_detection(
            Video={
                'S3Object': {
                    'Bucket': bucket_name,
                    'Name': file_name,
                }
            },
            MinConfidence=min_confidence,
            NotificationChannel={
                'SNSTopicArn': sns_topic_arn,
                'RoleArn': role_arn,
            },
        )

        job_id = response.get('JobId')
        print(f"[SUCCESS] Rekognition job started. JobId: {job_id}")

        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': f"Analysis successfully started for {file_name}",
                'jobId': job_id,
                'bucket': bucket_name,
                'file': file_name,
            }),
        }

    except KeyError as ke:
        print(f"[ERROR] KeyError parsing S3 event payload: {str(ke)}")
        return {
            'statusCode': 400,
            'body': json.dumps(f"Error parsing event: missing key {str(ke)}"),
        }
    except Exception as e:
        print(f"[CRITICAL ERROR] Failed to start Rekognition job for '{file_name}': {str(e)}")
        raise
