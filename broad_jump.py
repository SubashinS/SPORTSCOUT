import cv2
import mediapipe as mp
import numpy as np

# Initialize MediaPipe Pose
mp_pose = mp.solutions.pose

def calculate_jump_distance(landmarks):
    """Get hip x-coordinate for horizontal movement tracking"""
    return landmarks[mp_pose.PoseLandmark.LEFT_HIP].x

def run(video_path):
    """Process broad jump video and return score and distance"""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"Error: Could not open video file {video_path}")
        return 0, 0

    pose = mp_pose.Pose(min_detection_confidence=0.5, min_tracking_confidence=0.5)
    jump_count = 0
    max_jump_score = 0
    max_jump_distance_cm = 0
    baseline_x = None
    jump_detected = False
    
    # Scaling factor - calibrate based on your setup
    PIXEL_TO_CM = 0.3

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = pose.process(rgb)

        if results.pose_landmarks:
            landmarks = results.pose_landmarks.landmark
            hip_x = calculate_jump_distance(landmarks)

            if baseline_x is None:
                baseline_x = hip_x

            # Detect horizontal movement for broad jump
            horizontal_movement = abs(hip_x - baseline_x)
            
            if horizontal_movement > 0.15 and not jump_detected:
                jump_count += 1
                
                # Convert to distance
                jump_distance_pixels = horizontal_movement * frame.shape[1]
                jump_distance_cm = jump_distance_pixels * PIXEL_TO_CM
                
                # Calculate score (max 100)
                current_score = min(100, jump_distance_cm / 3)
                
                if current_score > max_jump_score:
                    max_jump_score = current_score
                    max_jump_distance_cm = jump_distance_cm
                
                jump_detected = True
                print(f"Jump {jump_count}: {jump_distance_cm:.1f}cm, Score: {current_score:.1f}")

            # Reset when returning to baseline
            if jump_detected and horizontal_movement < 0.05:
                jump_detected = False
                baseline_x = hip_x

            # Draw landmarks
            mp.solutions.drawing_utils.draw_landmarks(
                frame, results.pose_landmarks, mp_pose.POSE_CONNECTIONS)

            # Display info
            cv2.putText(frame, f"Jumps: {jump_count}", (30, 40),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
            cv2.putText(frame, f"Best: {max_jump_distance_cm:.1f}cm", (30, 80),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 0, 0), 2)
            cv2.putText(frame, f"Score: {max_jump_score:.1f}", (30, 120),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)

        cv2.imshow("Broad Jump Tracker", frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()
    
    return max_jump_score, jump_count

if __name__ == "__main__":
    score, count = run("test_video.mp4")
    print(f"Final Score: {score:.1f}, Jumps: {count}")
