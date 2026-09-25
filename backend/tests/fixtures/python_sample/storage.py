import boto3

s3 = boto3.client('s3')

def upload_avatar(file_path: str, user_id: int):
    """Uploads user avatar images to AWS S3 bucket."""
    s3.upload_file(file_path, "company-avatars-bucket", f"avatars/{user_id}.png")
