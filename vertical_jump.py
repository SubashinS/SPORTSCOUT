import cv2
import mediapipe as mp
mp_pose = mp.solutions.pose

def run(video_path):
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"Error: Could not open video file {video_path}")
        return 0
    pose = mp_pose.Pose(min_detection_confidence=0.5, min_tracking_confidence=0.5)
    jump_count = 0
    jump_score = 0
    baseline_y = None
    baseline_x = None 
    state = "STANDING"
    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = pose.process(rgb)
        if results.pose_landmarks:
            landmarks = results.pose_landmarks.landmark
            hip_y = landmarks[mp_pose.PoseLandmark.LEFT_HIP].y
            hip_x = landmarks[mp_pose.PoseLandmark.LEFT_HIP].x  
            if baseline_y is None:
                baseline_y = hip_y
            if baseline_x is None:
                baseline_x = hip_x
            if state == "STANDING":
                if hip_y > baseline_y + 0.05:
                    state = "CROUCHING"
            elif state == "CROUCHING":
                horizontal_movement = abs(hip_x - baseline_x)
                if hip_y < baseline_y - 0.05 and horizontal_movement < 0.1: 
                    state = "JUMPING"
                    jump_count += 1
                    jump_height = (baseline_y - hip_y) * 100  
                    jump_score = min(100, jump_height * 5)  
                elif horizontal_movement > 0.15: 
                    state = "STANDING"
            elif state == "JUMPING":
                if abs(hip_y - baseline_y) < 0.02:
                    state = "STANDING"
                    baseline_y = hip_y
                    baseline_x = hip_x

            # Draw landmarks on the frame
            mp.solutions.drawing_utils.draw_landmarks(
                frame, results.pose_landmarks, mp_pose.POSE_CONNECTIONS)
        # Overlay text on video
        cv2.putText(frame, f"Jumps: {jump_count}", (30, 50),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
        cv2.putText(frame, f"Score: {int(jump_score)}", (30, 100),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 255), 2)
        cv2.putText(frame, f"State: {state}", (30, 150),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 0), 2)
        cv2.imshow("Vertical Jump Test", frame)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()
    return jump_score, jump_count