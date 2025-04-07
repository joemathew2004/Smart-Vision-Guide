import requests  # Replace aiohttp with synchronous requests
import html
import math
import logging
from flask import Flask, request, jsonify
from flask_cors import CORS
import threading

app = Flask(__name__)
CORS(app)

GOOGLE_MAPS_API_KEY = "AIzaSyCvksfDM8-ye6ae6TkgLdYakxAMOtYTEe8"
DESTINATION_LAT = 10.0577764
DESTINATION_LNG = 76.6113135

current_lat = None
current_lng = None
current_step_index = 0
route_steps = []
location_lock = threading.Lock()

# Ensure logs are visible in console
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s', handlers=[logging.StreamHandler()])

def haversine_distance(lat1, lon1, lat2, lon2):
    R = 6371000
    lat1_rad = math.radians(lat1)
    lon1_rad = math.radians(lon1)
    lat2_rad = math.radians(lat2)
    lon2_rad = math.radians(lon2)
    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad
    a = math.sin(dlat / 2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    distance = R * c
    return round(distance, 2)

def get_directions(origin_lat, origin_lng, destination_lat, destination_lng):
    url = f"https://maps.googleapis.com/maps/api/directions/json?origin={origin_lat},{origin_lng}&destination={destination_lat},{destination_lng}&key={GOOGLE_MAPS_API_KEY}"
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        if data["status"] == "OK":
            return data["routes"][0]["legs"][0]
        else:
            logging.error(f"Google Maps API Error: {data['status']}")
            return None
    except requests.RequestException as e:
        logging.error(f"Error calling Google Maps API: {e}")
        return None

def format_instruction(step, distance_to_step, is_turning_point=False):
    instruction = html.unescape(step["html_instructions"]).replace('<b>', '').replace('</b>', '')
    distance_meters = int(distance_to_step)
    if is_turning_point:
        return f"turn {instruction.lower()} now"
    elif distance_meters > 50:
        return f"continue straight for {distance_meters} meters"
    else:
        return f"in {distance_meters} meters, {instruction.lower()}"

def update_current_step():
    global current_lat, current_lng, current_step_index, route_steps

    with location_lock:
        if current_lat is None or current_lng is None:
            return "no navigation update available"

        if not route_steps:
            leg = get_directions(current_lat, current_lng, DESTINATION_LAT, DESTINATION_LNG)
            if leg:
                route_steps = leg["steps"]
            else:
                logging.error("Failed to load route steps.")
                return "no navigation update available"

        dest_distance = haversine_distance(current_lat, current_lng, DESTINATION_LAT, DESTINATION_LNG)
        if dest_distance < 10:
            logging.info("You have reached your destination!")
            return "you have reached your destination"

        if 0 <= current_step_index < len(route_steps):
            step = route_steps[current_step_index]
            step_lat = step["end_location"]["lat"]
            step_lng = step["end_location"]["lng"]
            distance_to_step = haversine_distance(current_lat, current_lng, step_lat, step_lng)

            if distance_to_step < 20:
                current_step_index = min(current_step_index + 1, len(route_steps) - 1)
                if current_step_index < len(route_steps):
                    next_step = route_steps[current_step_index]
                    next_distance = next_step["distance"]["value"]
                    return f"{format_instruction(step, distance_to_step, True)} and then {format_instruction(next_step, next_distance)}"
                return format_instruction(step, distance_to_step, True)

            return format_instruction(step, distance_to_step)
        else:
            return "no navigation update available"

@app.route('/location', methods=['POST'])
def receive_location():
    global current_lat, current_lng
    logging.debug(f"Received POST request to /location from {request.remote_addr}")
    try:
        data = request.get_json(force=True)  # Force parsing even if Content-Type is missing
        logging.debug(f"Raw JSON data: {data}")
        if not data or 'latitude' not in data or 'longitude' not in data:
            logging.error(f"Invalid JSON: {data}")
            return jsonify({"status": "error", "message": "Missing latitude or longitude"}), 400
        with location_lock:
            current_lat = float(data['latitude'])
            current_lng = float(data['longitude'])
        logging.info(f"Received location: lat={current_lat}, lng={current_lng}")
        return jsonify({"status": "success", "message": "Location received"}), 200
    except ValueError as e:
        logging.error(f"Invalid coordinate format: {e}")
        return jsonify({"status": "error", "message": "Coordinates must be numbers"}), 400
    except Exception as e:
        logging.error(f"Error processing location: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

def run_flask_server(host='100.103.107.56', port=5001):
    app.run(host=host, port=port, debug=False, threaded=True)  # Use Flask's built-in server

if __name__ == "__main__":
    run_flask_server()