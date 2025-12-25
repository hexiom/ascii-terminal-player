from PIL import Image
from argparse import ArgumentParser
import numpy as np
import bz2, os, curses
from math import floor, ceil
from time import sleep, perf_counter

# ASCII_SET = '@%#*+=-:.'
ASCII_SET = " .:-=+*#%@"
SHADING_GAMMA = 2.2

def parse_frames(file_name: str):
    img_data = []
    img_width = -1
    img_height = -1
    fps = -1

    with open(file_name, "rb") as f:
        header = f.read(4).decode("ascii")
        if (header != "thba"):
            print(f"ERROR: The file specified is invalid and/or not a compressed video.")
            return 6
        
        fps = int.from_bytes(f.read(1))
        chunk_count = int.from_bytes(f.read(4))
        img_width = int.from_bytes(f.read(4))
        img_height = int.from_bytes(f.read(4))

        i = 0

        while (i < chunk_count):
            chunk_len = int.from_bytes(f.read(4))
            chunk_data = f.read(chunk_len)

            img_data.append(chunk_data)
            i += 1

    return (fps, img_data, img_width, img_height)

def decompress_frame(frame_data, img_width, img_height):
    decompressed = bz2.decompress(frame_data)
    im = Image.frombytes("L", (img_width, img_height), decompressed)

    return np.array(im)

def get_ascii_char_for_position(x: int, y: int, w_factor: int, h_factor: int, img_width: int, img_height: int, current_frame_data):
    mapped_x = x * w_factor
    mapped_y = y * h_factor

    x0 = floor(mapped_x)
    x1 = ceil(mapped_x)
    y0 = floor(mapped_y)
    y1 = ceil(mapped_y)

    dx = mapped_x - x0
    dy = mapped_y - y0

    if (y0 >= img_height or x0 >= img_width):
        return

    x1 = min(img_width - 1, x1)
    y1 = min(img_height - 1, y1)

    c_11 = current_frame_data[y0, x0]
    c_21 = current_frame_data[y0, x1]

    c_12 = current_frame_data[y1, x0]
    c_22 = current_frame_data[y1, x1]

    c1 = c_11 * (1 - dx) + c_21 * dx
    c2 = c_12 * (1 - dx) + c_22 * dx

    color = c1 * (1 - dy) + c2 * dy

    normalized = (color / 255) ** (1 / SHADING_GAMMA)
    shadow_idx = round(normalized * (len(ASCII_SET) - 1))

    return ASCII_SET[shadow_idx]

def render_debug(stdscr, current_frame: int, total_frame_count: int, fps_counter: int, is_frame_advance: bool, is_debug: bool):
    show_frame_counter = (is_debug or is_frame_advance)

    if (show_frame_counter):
        stdscr.addstr(1, 1, f" Frame {current_frame} / {total_frame_count} ")

    if (is_debug and fps_counter > 0):
        stdscr.addstr(2, 4, f" FPS: {fps_counter} ")

def main(stdscr):
    parser = ArgumentParser(description="A script to run a .bin compressed video file in the terminal window.")
    parser.add_argument("input_file", help="The input file.")
    parser.add_argument("--frame-advance", action="store_true")
    parser.add_argument("-d", "--debug", action="store_true")
    parser.add_argument("--wait-for-input", action="store_true")

    args = parser.parse_args()
    is_debug = args.debug
    is_frame_advance = args.frame_advance

    if (not os.path.exists(args.input_file)):
        print(f"ERROR: File \"{os.path.basename(args.input_file)}\" does not exist.")
        return 1

    curses.curs_set(0)
    stdscr.clear()
    
    (fps, img_data, img_width, img_height) = parse_frames(args.input_file)

    if (img_width <= 0 or img_height <= 0 or fps <= 0):
        print(f"ERROR: File specified is invalid.")
        return 6
    
    time_step = 1 / fps
    frame_counter = 0
    total_timer = 0
    fps_counter = -1

    if (args.wait_for_input):
        stdscr.addstr(1, 1, "Press any key to start...")
        stdscr.getch()

    start_time = perf_counter()
    last_rendered_frame = -1

    while (True):
        elapsed_time = perf_counter() - start_time
        current_frame = int(elapsed_time * fps)

        if (current_frame >= len(img_data)):
            break

        if (current_frame != last_rendered_frame):
            last_rendered_frame = current_frame

            stdscr.refresh()
            height, width = stdscr.getmaxyx()

            w_factor = img_width / width
            h_factor = img_height / height

            frame_data = decompress_frame(img_data[current_frame], img_width, img_height)
            t0 = perf_counter()

            for y in range(height):
                for x in range(width - 1):
                    stdscr.addch(y, x, get_ascii_char_for_position(x, y, w_factor, h_factor, img_width, img_height, frame_data))
            
            render_debug(stdscr, current_frame, len(img_data), fps_counter, is_frame_advance, is_debug)

            dt = perf_counter() - t0

            if (is_frame_advance):
                stdscr.getch()
                continue

            if (dt < time_step):
                time_to_wait = time_step - dt

                if (time_to_wait >= 0.001):
                    sleep(time_to_wait)
                
                dt = time_step
            
            frame_counter += 1
            total_timer += dt

            while (total_timer >= 1):
                total_timer -= 1
                fps_counter = frame_counter

                frame_counter = 0

curses.wrapper(main)