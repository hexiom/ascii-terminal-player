from argparse import ArgumentParser, ArgumentTypeError
import bz2, os, cv2
from sys import exit

DEFAULT_FPS = 10
DEFAULT_COMPRESSION_LEVEL = 4

def dimension_argument(value):
    value = ''.join(value.split())
    comma_separated = value.split(",")

    if (len(comma_separated) < 2):
        raise ArgumentTypeError(f"Invalid argument. The dimensions must be in the form (w, h)")

    try:
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
    parser.add_argument("--size", type=dimension_argument, help=f"The size of the resulting frames. Can be used to downscale or downscale the video. Must be in the form (w, h).")
    parser.add_argument("--compression-level", type=int, default=DEFAULT_COMPRESSION_LEVEL, help=f"The compression level of resulting binary file using bz2. Must be between 1 and 9. The default is {DEFAULT_COMPRESSION_LEVEL}")

    args = parser.parse_args()

    if (args.compression_level < 1 or args.compression_level > 9):
        print(f"ERROR: The compression level must be between 1 and 9 (got {args.compression_level}).")
        return 8
    
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

    if (args.size):
        width, height = args.size
    
    compressed_chunks = []

    while True:
        ret, frame = cap.read()
        if (not ret):
            break

        real_frame_idx = int(frame_idx / step)
        if (real_frame_idx > last_frame):
            if (args.size):
                frame = cv2.resize(frame, args.size, interpolation=cv2.INTER_AREA)

            gray_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            compressed = bz2.compress(gray_frame.tobytes(), compresslevel=args.compression_level)

            compressed_chunks.append(compressed)
            last_frame += 1
            cv2.imwrite(f"temp/frames/frame_{last_frame:04d}.png", gray_frame)
            print(f"Writing frame {last_frame}.")
        
        frame_idx += 1

    print(f"Created {len(compressed_chunks)} frames.")

    # The compression binary format
    # header (thba)
    # fps (u8)
    # number of chunks (u32)
    # width (u32)
    # height (u32)
    # list of chunks
    with open(args.output, "wb") as f:
        f.write("thba".encode("ascii"))
        f.write(args.fps.to_bytes(1))
        f.write(len(compressed_chunks).to_bytes(4))
        f.write(width.to_bytes(4))
        f.write(height.to_bytes(4))

        for chunk in compressed_chunks:
            f.write(len(chunk).to_bytes(4))
            f.write(chunk)
    
    return 0

if __name__ == "__main__":
    exit_code = main()
    exit(exit_code)