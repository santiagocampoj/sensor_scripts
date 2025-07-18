import argparse
import os
import datetime
import pyaudio
import wave

import boto3
import threading
from queue import Queue
import time  

from utils import *
from logging_config import setup_logging
import yaml


upload_queue = Queue()
last_successful_upload_time = time.time()





def get_device_index(logging, target_name="Sound Blaster Play! 3"):
    """Automatically find the input device index by name."""
    p = pyaudio.PyAudio()
    device_index = None

    for i in range(p.get_device_count()):
        device_info = p.get_device_info_by_index(i)
        logging.info(f"Device {i}: {device_info['name']}")
        if target_name.lower() in device_info['name'].lower() and device_info['maxInputChannels'] > 0:
            device_index = i
            logging.info(f"Found target device: {device_info['name']} (Index: {device_index})")
            break

    p.terminate()

    if device_index is None:
        raise ValueError(f"Target audio device '{target_name}' not found.")
    return device_index




def upload_worker(storage_s3_bucket_name, location_record, location_place, location_point, storage_output_wav_folder, logging):
    global last_successful_upload_time
    
    logging.info("Uploading to bucket S3")
    s3 = boto3.client("s3")
    
    while True:
        file_path = upload_queue.get()  # blocks until there's a file to upload
        if file_path is None:
            break
    
        try:
            object_key = f"{location_record}/{location_place}/{location_point}/{storage_output_wav_folder}/{os.path.basename(file_path)}"
            logging.info(f"Uploading {file_path} to s3://{storage_s3_bucket_name}/{object_key}")
            
            s3.upload_file(file_path, storage_s3_bucket_name, object_key)

            last_successful_upload_time = time.time()
            logging.info("Upload successful!")

        except Exception as e:
            error_message = f"Failed to upload file {file_path} to S3: {e}"
            logging.error(error_message)

        upload_queue.task_done()





def record_segment(stream, p, record_seconds, location_record, location_place, location_point, audio_format, audio_channels, audio_sample_rate, audio_chunk_size, storage_s3_bucket_name, storage_output_wav_folder, logging):
    """
    Record `record_seconds` of audio data from the stream,
    and save it to a .wav file named with the current datetime.
    Returns the full path to the saved file.
    """
    home_dir = os.getenv("HOME")
    frames = []

    # number of chunks for record_seconds
    num_chunks = int(audio_sample_rate / audio_chunk_size * record_seconds)
    logging.info(f"Chunk number: {num_chunks}")
    
    for _ in range(num_chunks):
        data = stream.read(audio_chunk_size, exception_on_overflow=False)
        frames.append(data)



    # output folder
    output_folder = os.path.join(home_dir, location_record, location_place, location_point, storage_output_wav_folder)
    logging.info(f"This is the output folder: {output_folder}")
    
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)
        logging.info(f"Making folder: {output_folder}")



    # filename with current time
    timestamp_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{timestamp_str}.wav"
    full_path = os.path.join(output_folder, filename)
    logging.info(f"This is the final full path: {full_path}")

    # save
    wf = wave.open(full_path, 'wb')
    wf.setnchannels(audio_channels)
    wf.setsampwidth(p.get_sample_size(audio_format))
    wf.setframerate(audio_sample_rate)
    wf.writeframes(b''.join(frames))
    wf.close()

    logging.info(f"Saved {record_seconds}-second recording to {full_path}")
    return full_path




def record_audio_continuous(device_index, location_record, location_place, location_point, audio_format, audio_channels, audio_sample_rate, audio_chunk_size, storage_s3_bucket_name, storage_output_wav_folder, logging, upload_s3, record_seconds=60):
    # recording setup
    p = pyaudio.PyAudio()
    stream = p.open(format=audio_format,
                    channels=audio_channels,
                    rate=audio_sample_rate,
                    frames_per_buffer=audio_chunk_size,
                    input=True,
                    input_device_index=device_index)

    # start background thread for uploading
    if upload_s3 is not None:
        logging.info("Uploading wav files to bucket S3")
        threading.Thread(
            target=upload_worker,
            args=(storage_s3_bucket_name, location_record, location_place, location_point, storage_output_wav_folder, logging),
            daemon=True
        ).start()
        logging.info("WAV FILE UPLOAD TO BUCKET S3")
    else:
        logging.warning("Not uploading wav files")



    try:
        while True:

            try:
                print(f"\nRecording continuous {record_seconds}-second segments... (Press Ctrl+C to stop)\n")
                logging.info(f"Recording continuous {record_seconds}-second segments...")
                file_path = record_segment(
                    stream, p, record_seconds, location_record, location_place, location_point,
                    audio_format, audio_channels, audio_sample_rate, audio_chunk_size,
                    storage_s3_bucket_name, storage_output_wav_folder, logging
                )
                logging.info(f"Enqueuing {file_path} for upload...")
                upload_queue.put(file_path)
                time.sleep(1)

                # remove the file after queuing for upload
                os.system(f"sudo rm -rf {file_path}")
                logging.info(f"Removed {file_path}")





            except Exception as segment_error:
                error_message = f"Error during segment processing: {segment_error}. Continuing to next segment."
                logging.error(error_message)
                time.sleep(1)
                continue


    except KeyboardInterrupt:
        logging.error("Recording stopped by user.")



    finally:
        upload_queue.put(None)
        stream.stop_stream()
        stream.close()
        p.terminate()
        logging.info("")



def check_uploads(logging, check_interval=60, threshold=70):
    while True:
        time.sleep(check_interval)
        elapsed = time.time() - last_successful_upload_time
        if elapsed > threshold:
            error_message = f"No upload in the last {elapsed:.0f} seconds."
            logging.error(error_message)
        else:
            logging.info(f"Upload check passed. Last upload was {elapsed:.0f} seconds ago.")



def upload_file_to_s3(file_path, bucket_name, logging):
    """
    Upload the local file_path to the given S3 bucket.
    """
    s3 = boto3.client('s3')
    # creating the paths 
    s3_path = file_path.split("/")[3:]
    # joint it back
    s3_path = "/".join(s3_path)
    s3_full_path = os.path.join(s3_path)
    
    logging.info(f"Uploading {file_path} to s3://{bucket_name}/{s3_path}")
    try:
        s3.upload_file(file_path, bucket_name, s3_path)
        logging.info("Upload successful!")
    
    except Exception as e:
        logging.error(f"Failed to upload to S3: {e}")



def arg_parser():
    """
    Parse command-line arguments.
    Use --time to set how many seconds each continuous segment should be.
    Defaults to 60 seconds if not specified.
    """
    parser = argparse.ArgumentParser(description='Audio recording script')
    parser.add_argument('-t', '--time', type=int, default=60,
                        help='Length (in seconds) of each continuous recording. Default is 60.')
    parser.add_argument('-u', '--upload-S3', action='store_true', default=False,
                        help='If provided, upload the final CSV to S3.')
    return parser.parse_args()




def main():
    try:
        logging = setup_logging(script_name="record_audio")
        args = arg_parser()

        logging.info("Starting process!!")
        logging.info("")

        upload_s3 = args.upload_S3 if args.upload_S3 else None
        record_seconds = args.time if args.time else 60

        logging.info(f"Upload to bucket S3: {upload_s3}")
        logging.info(f"Recording {record_seconds} seconds")

        # device index
        try:
            device_index = get_device_index(logging)
            logging.info(f"Using device index: {device_index}")
        except Exception as e:
            logging.error(f"Error getting the device index: {e}")
            return



        # configuration
        try:
            location_record, location_place, location_point, audio_format, \
            audio_channels, audio_sample_rate, audio_chunk_size, storage_s3_bucket_name, \
            storage_output_wav_folder = load_config_record('config.yaml')

            if audio_format == "pyaudio.paInt16":
                audio_format = pyaudio.paInt16

        except Exception as e:
            logging.error(f"Error loading config: {e}")
            return

        #checkout
        if upload_s3:
            threading.Thread(
                target=check_uploads,
                args=(logging,),
                daemon=True
            ).start()
        logging.info("Started upload checkout thread.")



        logging.info("")
        logging.info("Entering recording audio workflow!")
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

            logging,

            upload_s3=upload_s3,
            record_seconds=record_seconds
        )

    except Exception as e:
        logging.error(f"An unexpected error occurred: {e}")


if __name__ == "__main__":
    main()
