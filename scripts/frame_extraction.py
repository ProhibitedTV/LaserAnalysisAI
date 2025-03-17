import cv2
import os

def extract_frames(video_path, output_folder="data/frames", frame_interval=5, progress_callback=None):
    """Extracts frames from a video and saves them as images."""
    
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

    while True:
        ret, frame = cap.read()
        if not ret:
            break  # End of video

        # Save every 'frame_interval' frames
        if frame_count % frame_interval == 0:
            frame_filename = os.path.join(output_folder, f"frame_{saved_frames:04d}.jpg")
            cv2.imwrite(frame_filename, frame)
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
