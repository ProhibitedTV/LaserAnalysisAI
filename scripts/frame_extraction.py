"""
Frame Extraction module for extracting frames from videos.
This module saves frames at regular intervals and supports progress updates.
"""

import cv2
import os
from concurrent.futures import ThreadPoolExecutor

def save_frame(frame, frame_filename):
    """Saves a single frame to the specified file."""
    cv2.imwrite(frame_filename, frame)

def extract_frames(video_path, output_folder="data/frames", frame_interval=5, progress_callback=None):
    """
    Extracts frames from a video and saves them as images.

    Args:
        video_path (str): Path to the video file.
        output_folder (str): Directory to save the extracted frames.
        frame_interval (int): Interval between frames to save.
        progress_callback (callable, optional): Function to update progress.
    """
    
    if not os.path.exists(video_path):
        print(f"Error: Video file not found! {video_path}")
        return

    # Create output directory if it doesn't exist
    os.makedirs(output_folder, exist_ok=True)

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print("Error: Could not open video.")
        return

    frame_count = 0
    saved_frames = 0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    # Use ThreadPoolExecutor for parallel frame saving
    with ThreadPoolExecutor() as executor:
        while True:
            ret, frame = cap.read()
            if not ret:
                break  # End of video

            # Save every 'frame_interval' frames
            if frame_count % frame_interval == 0:
                frame_filename = os.path.join(output_folder, f"frame_{saved_frames:04d}.jpg")
                executor.submit(save_frame, frame, frame_filename)
                saved_frames += 1

            frame_count += 1

            # Update progress
            if progress_callback:
                progress_callback(int((frame_count / total_frames) * 100))

    cap.release()
    print(f"Extracted {saved_frames} frames from {video_path} into {output_folder}")

if __name__ == "__main__":
    video_path = "data/sample_video.mp4"  # Change this to the correct video path
    extract_frames(video_path)
