from argparse import ArgumentParser, ArgumentTypeError
import os, cv2
import lz4.frame as lz4f
from sys import exit

DEFAULT_FPS = 10

def dimension_argument(value):
    value = ''.join(value.split())
    comma_separated = value.split(",")

    try:
        if (len(comma_separated) == 1 or not comma_separated[1]):
            return (int(comma_separated[0]), -1)
        width = int(comma_separated[0])
        height = int(comma_separated[1])

        return (width, height)
    except ValueError as e:
        raise ArgumentTypeError(f"Invalid argument. The dimensions must be of type integer.")

def main():
    parser = ArgumentParser(description="A script that compresses all of the frames of Bad Apple into one binary file.")
    parser.add_argument("input_file", help="The input video file to compress into a file.")
    parser.add_argument("-o", "--output", required=True, help="The output binary file.")
    parser.add_argument("--fps", type=int, default=DEFAULT_FPS, help=f"The FPS at which the frames of the video will be rendered. The default is {DEFAULT_FPS}")
    parser.add_argument("--size", type=dimension_argument, help=f"The size of the resulting frames. Can be used to downscale or downscale the video. Must be in the form \"w, h\".")
    parser.add_argument("--no-compression", action="store_true", help="Disables compression for the .bin file. The compression level has no effect with this enabled.")
    parser.add_argument("-d", "--debug", action="store_true")

    args = parser.parse_args()
    is_debug = args.debug
    
    if (not os.path.exists(args.input_file)):
        print(f"ERROR: File \"{os.path.basename(args.input_file)}\" does not exist.")
        return 2
    elif (os.path.exists(args.output)):
        res = input(f"The file {os.path.basename(args.output)} already exists. Replace [Y/N]: ").lower()

        if (res == "n"):
            return 0
        elif (res.lower() != "y"):
            print("ABORTED.")
            return 0
    
    cap = cv2.VideoCapture(args.input_file)
    frame_idx = 0
    last_frame = 0
    width = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
    height = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
    step = cap.get(cv2.CAP_PROP_FPS) / args.fps
    size = args.size

    if (size):
        if (size[1] < 0):
            height_ratio = height / width
            size = (size[0], round(size[0] * height_ratio))
        width, height = size
    
    if (is_debug):
        print(f"The frame size is ({width}, {height}).")
    
    chunk_list = []

    if (is_debug):
        os.makedirs("debug/temp", exist_ok=True)

    while True:
        ret, frame = cap.read()
        if (not ret):
            break

        real_frame_idx = int(frame_idx / step)
        if (real_frame_idx > last_frame):
            if (size):
                frame = cv2.resize(frame, size, interpolation=cv2.INTER_AREA)

            gray_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            bytes_data = gray_frame.tobytes()

            if (not args.no_compression):
                bytes_data = lz4f.compress(bytes_data)

            chunk_list.append(bytes_data)
            last_frame += 1
            print(f"Writing frame {last_frame}.")

            if (is_debug):
                cv2.imwrite(f"debug/temp/frame_{last_frame:04d}.png", gray_frame)
                
        frame_idx += 1

    print(f"Created {len(chunk_list)} frames.")

    # The compression binary format
    # header (thba)
    # fps (u8)
    # has_compression (0|1)
    # number of chunks (u32)
    # width (u32)
    # height (u32)
    # list of chunks
    with open(args.output, "wb") as f:
        f.write("thba".encode("ascii"))
        f.write(args.fps.to_bytes(1))
        f.write(int(not args.no_compression).to_bytes(1))
        f.write(len(chunk_list).to_bytes(4))
        f.write(width.to_bytes(4))
        f.write(height.to_bytes(4))

        for chunk in chunk_list:
            f.write(len(chunk).to_bytes(4))
            f.write(chunk)
    
    return 0

if __name__ == "__main__":
    exit_code = main()
    exit(exit_code)