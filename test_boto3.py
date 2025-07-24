import boto3
s3 = boto3.client('s3')
s3.upload_file('test_upload.txt', 'demo-prototype-aac-2025', 'test/test_upload.txt')
print('Upload successful!')