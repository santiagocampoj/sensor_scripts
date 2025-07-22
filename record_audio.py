import argparse
import os
import datetime
import pyaudio
import wave
import time  
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




def get_device_index(target_name="stm32max98088"):
    """Automatically find the input device index by name."""
    p = pyaudio.PyAudio()
    device_index = None

    for i in range(p.get_device_count()):
        device_info = p.get_device_info_by_index(i)
        print(f"Device {i}: {device_info['name']}")
        if target_name.lower() in device_info['name'].lower() and device_info['maxInputChannels'] > 0:
            device_index = i
            print(f"Found target device: {device_info['name']} (Index: {device_index})")
            break

    p.terminate()

    if device_index is None:
        raise ValueError(f"Target audio device '{target_name}' not found.")
    return device_index




def record_segment(stream, p, record_seconds, location_record, location_place, location_point,
                   audio_format, audio_channels, audio_sample_rate, audio_chunk_size,
                   storage_s3_bucket_name, storage_output_wav_folder):
    
    home_dir = os.getenv("HOME")
    frames = []

    num_chunks = int(audio_sample_rate / audio_chunk_size * record_seconds)
    print(f"Chunk number: {num_chunks}")
    
    for _ in range(num_chunks):
        data = stream.read(audio_chunk_size, exception_on_overflow=False)
        frames.append(data)

    output_folder = os.path.join(home_dir, location_record, location_place, location_point, storage_output_wav_folder)
    print(f"This is the output folder: {output_folder}")
    
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)
        print(f"Making folder: {output_folder}")

    timestamp_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{timestamp_str}.wav"
    full_path = os.path.join(output_folder, filename)
    print(f"This is the final full path: {full_path}")

    wf = wave.open(full_path, 'wb')
    wf.setnchannels(audio_channels)
    wf.setsampwidth(p.get_sample_size(audio_format))
    wf.setframerate(audio_sample_rate)
    wf.writeframes(b''.join(frames))
    wf.close()

    print(f"Saved {record_seconds}-second recording to {full_path}")
    return full_path




def upload_file_to_s3(file_path, bucket_name):
    s3 = boto3.client('s3')
    s3_path = "/".join(file_path.split("/")[3:])
    print(f"Uploading {file_path} to s3://{bucket_name}/{s3_path}")
    try:
        s3.upload_file(file_path, bucket_name, s3_path)
        print("Upload successful!")
    except Exception as e:
        print(f"Failed to upload to S3: {e}")




def record_audio_continuous(device_index, location_record, location_place, location_point,
                            audio_format, audio_channels, audio_sample_rate, audio_chunk_size,
                            storage_s3_bucket_name, storage_output_wav_folder,
                            upload_s3, record_seconds=60):

    p = pyaudio.PyAudio()
    stream = p.open(format=audio_format,
                    channels=audio_channels,
                    rate=audio_sample_rate,
                    frames_per_buffer=audio_chunk_size,
                    input=True,
                    input_device_index=device_index)

    try:
        while True:
            print(f"\nRecording {record_seconds}-second segment... (Press Ctrl+C to stop)")
            file_path = record_segment(
                stream, p, record_seconds,
                location_record, location_place, location_point,
                audio_format, audio_channels, audio_sample_rate, audio_chunk_size,
                storage_s3_bucket_name, storage_output_wav_folder
            )

            if upload_s3:
                upload_file_to_s3(file_path, storage_s3_bucket_name)

            os.system(f"sudo rm -rf {file_path}")
            print(f"Removed {file_path}")
            time.sleep(1)

    except KeyboardInterrupt:
        print("Recording stopped by user.")
    finally:
        stream.stop_stream()
        stream.close()
        p.terminate()




def arg_parser():
    parser = argparse.ArgumentParser(description='Audio recording script')
    parser.add_argument('-t', '--time', type=int, default=60,
                        help='Length (in seconds) of each continuous recording. Default is 60.')
    parser.add_argument('-u', '--upload-S3', action='store_true', default=False,
                        help='If provided, upload the final WAV to S3.')
    return parser.parse_args()



def main():
    try:
        args = arg_parser()

        print("Starting process!!\n")

        upload_s3 = args.upload_S3 if args.upload_S3 else None
        record_seconds = args.time if args.time else 60

        print(f"Upload to bucket S3: {upload_s3}")
        print(f"Recording {record_seconds} seconds")



        try:
            device_index = get_device_index()
            print(f"Using device index: {device_index}")
        except Exception as e:
            print(f"Error getting the device index: {e}")
            return


        try:
            location_record, location_place, location_point, audio_format, \
            audio_channels, audio_sample_rate, audio_chunk_size, storage_s3_bucket_name, \
            storage_output_wav_folder = load_config_record('config.yaml')

            if audio_format == "pyaudio.paInt16":
                audio_format = pyaudio.paInt16

        except Exception as e:
            print(f"Error loading config: {e}")
            return



        print("Entering recording audio workflow!\n")
        record_audio_continuous(
            device_index,
            location_record,
            location_place,
            location_point,
            audio_format,
            audio_channels,
            audio_sample_rate,
            audio_chunk_size,
            storage_s3_bucket_name,
            storage_output_wav_folder,
            upload_s3=upload_s3,
            record_seconds=record_seconds
        )

    except Exception as e:
        print(f"An unexpected error occurred: {e}")

if __name__ == "__main__":
    main()
