import cv2
import mediapipe as mp

BENCHMARK_800M = 120.0
START_LINE_X = 50
FINISH_LINE_X = 550

mp_pose = mp.solutions.pose

def calculate_score(total_time):
    if total_time <= 0:
        return 0
    score = min((BENCHMARK_800M / total_time) * 10, 10)
    return round(score, 2)

def run(video_path):
    pose = mp_pose.Pose(min_detection_confidence=0.5, min_tracking_confidence=0.5)
    
    cap = cv2.VideoCapture(video_path) if video_path else cv2.VideoCapture(0)
    fps = cap.get(cv2.CAP_PROP_FPS) if video_path else 30

    if not cap.isOpened():
        return 0, 0, 0

    running = False
    start_frame = None
    end_frame = None
    score = 0
    frame_count = 0
    attempts = 1

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break

        frame_count += 1
        frame = cv2.resize(frame, (640, 480))
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = pose.process(rgb_frame)

        hip_x = None
        if results.pose_landmarks:
            hip = results.pose_landmarks.landmark[mp_pose.PoseLandmark.LEFT_HIP]
            hip_x = int(hip.x * frame.shape[1])
            hip_y = int(hip.y * frame.shape[0])
            cv2.circle(frame, (hip_x, hip_y), 10, (0, 255, 0), -1)

        if not running and hip_x is not None and hip_x >= START_LINE_X:
            running = True
            start_frame = frame_count

        if running and hip_x is not None and hip_x >= FINISH_LINE_X:
            end_frame = frame_count
            total_time = (end_frame - start_frame) / fps
            score = calculate_score(total_time)
            print(f"800m Run Finished! Time: {total_time:.2f}s | Score: {score}/10")
            break

        elapsed = 0 if not running else (frame_count - start_frame) / fps
        cv2.putText(frame, f"Elapsed: {elapsed:.2f}s", (10, 70), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 0, 0), 2)

        cv2.line(frame, (START_LINE_X, 0), (START_LINE_X, frame.shape[0]), (0, 255, 0), 2)
        cv2.line(frame, (FINISH_LINE_X, 0), (FINISH_LINE_X, frame.shape[0]), (0, 0, 255), 2)

        cv2.imshow("800m Run", frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()
    return score, attempts, total_time
