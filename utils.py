
import yaml
import boto3



def load_config(yaml_path: str) -> dict:
    with open(yaml_path, 'r') as file:
        config = yaml.safe_load(file)
    return config



def load_config_record(yaml_path: str) -> dict:
    with open(yaml_path, 'r') as file:
        config = yaml.safe_load(file)

        location_record = config["location"]["record"]
        location_place = config['location']['place']
        location_point = config['location']['point']


        audio_format = config['audio']['format']
        audio_channels = config['audio']['channels']
        audio_sample_rate = config['audio']['sample_rate']
        audio_chunk_size = config['audio']['chunk_size']


        storage_s3_bucket_name = config['storage']['s3_bucket_name'] 
        storage_output_wav_folder = config['storage']['output_wav_folder']


    return location_record, location_place, location_point, audio_format, audio_channels, audio_sample_rate, audio_chunk_size, storage_s3_bucket_name, storage_output_wav_folder

