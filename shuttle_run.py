import cv2
import mediapipe as mp
import time

BENCHMARK_TIME = 10.0
START_LINE_X = 50
FINISH_LINE_X = 550
MOVEMENT_THRESHOLD = 2

mp_pose = mp.solutions.pose

def calculate_shuttle_run_score(total_time, benchmark_time=BENCHMARK_TIME, max_score=10):
    if total_time <= 0:
        return 0
    score = (benchmark_time / total_time) * max_score
    return round(min(score, max_score), 2)

def run(video_path):
    pose = mp_pose.Pose(min_detection_confidence=0.5, min_tracking_confidence=0.5)
    cap = cv2.VideoCapture(video_path) if video_path else cv2.VideoCapture(0)

    if not cap.isOpened():
        return 0, 0, 0

    prev_hip_x = None
    running = False
    start_time = None
    total_time = 0
    score = 0
    attempts = 1
    movement_detected = False
    max_distance_covered = 0
    last_significant_move_time = None

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break

        frame = cv2.resize(frame, (640, 480))
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = pose.process(rgb_frame)

        hip_x = None
        if results.pose_landmarks:
            hip = results.pose_landmarks.landmark[mp_pose.PoseLandmark.LEFT_HIP]
            hip_x = int(hip.x * frame.shape[1])
            hip_y = int(hip.y * frame.shape[0])
            cv2.circle(frame, (hip_x, hip_y), 10, (0, 255, 0), -1)

            # Track maximum distance for scoring
            if hip_x > max_distance_covered:
                max_distance_covered = hip_x

        # Movement detection and start timing
        if hip_x is not None and not running:
            if prev_hip_x is not None:
                if abs(hip_x - prev_hip_x) > MOVEMENT_THRESHOLD:
                    running = True
                    start_time = time.time()
                    movement_detected = True
                    print(f"Movement detected, starting timer...")
            prev_hip_x = hip_x

        # Continue tracking movement during the run
        if running and hip_x is not None and prev_hip_x is not None:
            if abs(hip_x - prev_hip_x) > MOVEMENT_THRESHOLD:
                last_significant_move_time = time.time()
            prev_hip_x = hip_x

        # Finish conditions - multiple ways to end the run
        if running and start_time:
            current_time = time.time()
            elapsed_time = current_time - start_time

            # Condition 1: Reached finish line
            if hip_x is not None and hip_x >= FINISH_LINE_X:
                total_time = elapsed_time
                score = calculate_shuttle_run_score(total_time)
                print(f"Shuttle Run Finished (reached finish)! Time: {total_time:.2f}s | Score: {score}/10")
                break

            # Condition 2: No significant movement for 3 seconds (completed exercise)
            elif last_significant_move_time and (current_time - last_significant_move_time) > 3.0:
                total_time = elapsed_time
                # Adjust score based on distance covered
                distance_factor = min(1.0, max_distance_covered / FINISH_LINE_X)
                base_score = calculate_shuttle_run_score(total_time)
                score = base_score * distance_factor
                score = max(1.0, min(score, 10.0))  # Ensure minimum score of 1
                print(f"Shuttle Run Finished (stopped moving)! Time: {total_time:.2f}s | Score: {score}/10")
                break

            # Condition 3: Maximum time limit reached (15 seconds)
            elif elapsed_time > 15.0:
                total_time = elapsed_time
                # Give partial credit based on distance covered
                distance_factor = min(1.0, max_distance_covered / FINISH_LINE_X)
                score = max(1.0, 5.0 * distance_factor)  # Up to 5 points for partial completion
                print(f"Shuttle Run Finished (time limit)! Time: {total_time:.2f}s | Score: {score}/10")
                break

        # Auto-start if movement is detected but running hasn't started
        if not running and hip_x is not None and prev_hip_x is not None:
            if abs(hip_x - prev_hip_x) > MOVEMENT_THRESHOLD and not movement_detected:
                running = True
                start_time = time.time()
                movement_detected = True

        # Display elapsed time
        elapsed = 0 if start_time is None else time.time() - start_time
        cv2.putText(frame, f"Elapsed: {elapsed:.2f}s", (10, 70), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 0, 0), 2)

        # Show score if completed
        if score > 0:
            cv2.putText(frame, f"Score: {score:.1f}/10", (10, 110), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)

        # Draw start and finish lines
        cv2.line(frame, (START_LINE_X, 0), (START_LINE_X, frame.shape[0]), (0, 255, 0), 2)
        cv2.line(frame, (FINISH_LINE_X, 0), (FINISH_LINE_X, frame.shape[0]), (0, 0, 255), 2)

        cv2.imshow("Shuttle Run", frame)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()

    # Ensure we always return a valid score
    if score == 0 and movement_detected:
        # Give minimum score for attempting
        total_time = max(total_time, 1.0)
        score = 1.0
    elif score == 0:
        # No movement detected, but still give minimal credit
        total_time = 1.0
        score = 0.5

    return score, attempts, total_time
