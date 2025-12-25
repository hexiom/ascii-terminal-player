from PIL import Image
from argparse import ArgumentParser
import numpy as np
import bz2, os, curses
from math import floor, ceil
from time import sleep, perf_counter

ASCII_SET = '@%#*+=-:.'
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

def to_grayscale(r: int, g: int, b: int) -> int:
    return 0.299 * r + 0.587 * g + 0.114 * b

def main(stdscr):
    parser = ArgumentParser(description="A script to run a .bin compressed video file in the terminal window.")
    parser.add_argument("input_file", help="The input file.")

    args = parser.parse_args()

    if (not os.path.exists(args.input_file)):
        print(f"ERROR: File \"{os.path.basename(args.input_file)}\" does not exist.")
        return 1

    curses.curs_set(0)
    stdscr.clear()
    
    current_frame = 0

    (fps, img_data, img_width, img_height) = parse_frames(args.input_file)

    if (img_width == -1 or img_height == -1 or fps == -1):
        print(f"ERROR: File specified is invalid.")
        return 6
    
    time_step = 1 / fps

    while True:
        stdscr.refresh()
        height, width = stdscr.getmaxyx()

        w_factor = img_width / width
        h_factor = img_height / height

        frame_data = decompress_frame(img_data[current_frame], img_width, img_height)
        
        t0 = perf_counter()
        for y in range(height):
            for x in range(width - 1):
                mapped_x = x * w_factor
                mapped_y = y * h_factor

                x0 = floor(mapped_x)
                x1 = ceil(mapped_x)
                y0 = floor(mapped_y)
                y1 = ceil(mapped_y)

                dx = mapped_x - x0
                dy = mapped_y - y0

                if (y0 >= img_height or x0 >= img_width):
                    continue

                x1 = min(img_width - 1, x1)
                y1 = min(img_height - 1, y1)

                c_11 = frame_data[y0, x0]
                c_21 = frame_data[y0, x1]

                c_12 = frame_data[y1, x0]
                c_22 = frame_data[y1, x1]

                c1 = c_11 * (1 - dx) + c_21 * dx
                c2 = c_12 * (1 - dx) + c_22 * dx

                color = c1 * (1 - dy) + c2 * dy

                normalized = (color / 255) ** (1 / SHADING_GAMMA)
                shadow_idx = round(normalized * (len(ASCII_SET) - 1))

                stdscr.addch(y, x, ASCII_SET[shadow_idx])

        dt = perf_counter() - t0
        current_frame += 1

        if (dt < time_step):
            sleep(time_step - dt)

curses.wrapper(main)