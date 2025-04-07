from ultralytics import YOLO
import cv2
import time


'''rf = Roboflow(api_key="qYc8x0NgHSgY0WYP36Z2")
project = rf.workspace().project("wallcoloring")
roboflow_model = project.version(1).model
'''
def process_frame(frame, model, allowed_classes, previous_objects, print_delay):
    """Processes a frame, performs object detection, and returns a message."""

    global last_processed_time  # Use the global last_processed_time
    general_delay = 0  # Define the general delay

    results = model(frame, verbose=False)
    detections = results[0].boxes

    closest_object = None
    closest_bbox = None

    # Corrected check for empty detections
    if detections and len(detections) > 0:
        for box in detections:
            class_id = int(box.cls[0])
            if class_id in allowed_classes:
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                label = model.names[class_id]

                if closest_object is None:
                    closest_object = label
                    closest_bbox = (x1, y1, x2, y2)
                else:
                    current_center_x = (x1 + x2) / 2
                    previous_center_x = (closest_bbox[0] + closest_bbox[2]) / 2

                    if abs(frame.shape[1] / 2 - current_center_x) < abs(frame.shape[1] / 2 - previous_center_x):
                        closest_object = label
                        closest_bbox = (x1, y1, x2, y2)

        if closest_object and closest_bbox:
            object_key = closest_object
            current_time = time.time()

            if (current_time - last_processed_time) > general_delay:  # check general delay
                if object_key not in previous_objects or (current_time - previous_objects[object_key]) > print_delay:
                    x1, y1, x2, y2 = closest_bbox

                    frame_center_x = frame.shape[1] / 2
                    box_center_x = (x1 + x2) / 2

                    if box_center_x < frame_center_x - 50:
                        position = "at left"
                        direction_instruction = "turn right"
                    elif box_center_x > frame_center_x + 50:
                        position = "at right"
                        direction_instruction = "turn left"
                    else:
                        position = "directly ahead"
                        direction_instruction = "proceed with caution"

                    output_message = f"{closest_object} {position}, {direction_instruction}"
                    last_processed_time = current_time  # update last processed time
                    return output_message
                else:
                    return "Same object delay not met."
            else:
                return "General delay not met."
    else:  # Handle no detections
        # Attempt wall detection using Roboflow
        '''try:
            _, encoded_image = cv2.imencode('.jpg', frame)
            result = roboflow_model.predict(encoded_image.tobytes(), confidence=40, overlap=30).json()

            labels = [item["class"] for item in result["predictions"]]
            if "Wall" in labels:
                return "Wall detected, proceed with caution"
            else:
                return "No detections"
        except Exception as e:
            print(f"Error during wall detection: {e}")
            '''
        return "No detections"

    return "No detections"

def load_model():
    """Loads the YOLO model."""
    model = YOLO("yolov8n-oiv7.pt")
    return model

def get_allowed_classes():
    """Returns the allowed classes."""
    allowed_classes = {7, 19, 34, 42, 43, 52, 54, 57, 62, 63, 70, 73, 90, 100, 104,
                       107, 127, 128, 130, 136, 147, 148, 153, 160, 164, 165, 190, 212, 216,
                       257, 264, 290, 302,304, 318, 322, 335, 342, 345, 354, 364, 381, 419,453, 477, 489,
                       492, 503, 510, 514, 522, 548, 549, 553, 550, 558, 564, 567, 575, 583,
                       587, 588, 594}
    return allowed_classes

def get_previous_objects():
    """Returns an empty dictionary for previous objects."""
    return {}

def get_print_delay():
    """Returns the print delay."""
    return 3

# Initialize last_processed_time outside the function
last_processed_time = 0