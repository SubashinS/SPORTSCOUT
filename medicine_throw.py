import cv2
import mediapipe as mp
import numpy as np

mp_pose = mp.solutions.pose

def run(video_path=None, throw_threshold=0.06, release_threshold=0.025,
        min_throw_distance=10, cooldown_limit=10, frame_skip=1):
    cap = cv2.VideoCapture(video_path) if video_path else cv2.VideoCapture(0)

    if not cap.isOpened():
        print(f"Error: Could not open video source {video_path or 'webcam'}")
        return 0

    pose = mp_pose.Pose(min_detection_confidence=0.5, min_tracking_confidence=0.5)

    throw_count = 0
    throw_score = 0
    baseline = None
    max_throw = None
    cooldown = 0
    state = "READY"
    frame_idx = 0

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break

        # Resize frame to 640x480 for faster processing
        frame = cv2.resize(frame, (640, 480))

        # Skip frames to reduce processing rate
        if frame_idx % frame_skip != 0:
            frame_idx += 1
            continue
        frame_idx += 1

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = pose.process(rgb)

        if results.pose_landmarks:
            landmarks = results.pose_landmarks.landmark

            wrist_x = landmarks[mp_pose.PoseLandmark.RIGHT_WRIST].x

            if baseline is None:
                baseline = wrist_x

            if cooldown > 0:
                cooldown -= 1

            if state == "READY" and wrist_x < 0.55:
                state = "PRE_THROW"
            elif state == "PRE_THROW" and wrist_x > baseline + throw_threshold:
                state = "THROWING"
                max_throw = wrist_x
            elif state == "THROWING":
                if wrist_x > max_throw:
                    max_throw = wrist_x
                if wrist_x < max_throw - release_threshold:
                    dist = (max_throw - baseline) * 100
                    if dist > min_throw_distance and cooldown == 0:
                        score_multiplier = 7
                        throw_score = min(100, dist * score_multiplier)
                        throw_count += 1
                        cooldown = cooldown_limit
                    baseline = wrist_x
                    max_throw = None
                    state = "READY"

            mp.solutions.drawing_utils.draw_landmarks(frame, results.pose_landmarks, mp_pose.POSE_CONNECTIONS)

        # Display overlay information
        cv2.putText(frame, f"Throws: {throw_count}", (30, 50),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
        cv2.putText(frame, f"Score: {int(throw_score)}", (30, 100),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 215, 255), 2)
        cv2.putText(frame, f"State: {state}", (30, 150),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 0), 2)

        cv2.imshow("Medicine Ball Throw Analysis", frame)

        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()

    return throw_score


if __name__ == "__main__":
    # For testing live webcam feed
    score = run(video_path=None,
                throw_threshold=0.06,
                release_threshold=0.025,
                min_throw_distance=10,
                cooldown_limit=10,
                frame_skip=1)
    print("Final Score:", score)
