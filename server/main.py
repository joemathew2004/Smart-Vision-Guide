import socket
import struct
import cv2
import numpy as np
import threading
import predictions
from gps_handler import update_current_step, run_flask_server

SERVER_HOST = '100.103.107.56'
SOCKET_PORT = 5000

def combine_results(pred_result, gps_result):
    """Intelligently combine prediction and GPS results for a blind person."""
    pred_result = pred_result if pred_result else "no obstacles detected"
    if pred_result != "no obstacles detected":
        pred_result = f"{pred_result}"

    if gps_result == "no navigation update available":
        return pred_result
    elif "you have reached your destination" in gps_result:
        return f"{pred_result}. {gps_result}"
    else:
        return f"{pred_result}. {gps_result}"

def handle_client(client_socket, model, allowed_classes):
    connection = client_socket.makefile('rb')
    try:
        while True:
            size_data = connection.read(4)
            if not size_data:
                break

            size = struct.unpack('>L', size_data)[0]
            frame_bytes = connection.read(size)

            img_np = np.frombuffer(frame_bytes, dtype=np.uint8)
            frame = cv2.imdecode(img_np, cv2.IMREAD_COLOR)

            if frame is not None:
                previous_objects = predictions.get_previous_objects()
                print_delay = predictions.get_print_delay()
                pred_result = predictions.process_frame(frame, model, allowed_classes, previous_objects, print_delay)

                gps_result = update_current_step()  # Synchronous call

                combined_result = combine_results(pred_result, gps_result)
                print(f"Processed: {combined_result}")

                response_bytes = combined_result.encode('utf-8')
                response_size = len(response_bytes)
                response_size_data = struct.pack('>L', response_size)
                client_socket.sendall(response_size_data)
                client_socket.sendall(response_bytes)
            else:
                print("Error decoding frame.")
                break
    except Exception as e:
        print(f"Error handling client: {e}")
    finally:
        connection.close()
        client_socket.close()

def server_main(host, port, model, allowed_classes):
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.bind((host, port))
    server_socket.listen(1)
    print(f"Socket server listening on {host}:{port}")

    try:
        while True:
            client_socket, addr = server_socket.accept()
            print(f"Connection from: {addr}")
            client_thread = threading.Thread(target=handle_client, args=(client_socket, model, allowed_classes))
            client_thread.start()
    except KeyboardInterrupt:
        print("Socket server shutting down.")
    finally:
        server_socket.close()

if __name__ == "__main__":
    model = predictions.load_model()
    allowed_classes = predictions.get_allowed_classes()

    flask_thread = threading.Thread(target=run_flask_server, args=('0.0.0.0', 5001))
    flask_thread.daemon = True
    flask_thread.start()

    server_main(SERVER_HOST, SOCKET_PORT, model, allowed_classes)