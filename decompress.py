import sys, os
import lz4.frame as lz4f
from PIL import Image
from argparse import ArgumentParser

def main():
    parser = ArgumentParser(description="A script to run a .bin compressed video file in the terminal window.")
    parser.add_argument("input_file", help="The input file.")
    parser.add_argument("-o", "--output", required=True, help="The output folder for the frames.")
    parser.add_argument("-v", "--verbose", action="store_true")

    args = parser.parse_args()
    is_verbose = args.verbose
    
    if (not os.path.exists(args.input_file)):
        print(f"ERROR: File \"{os.path.basename(args.input_file)}\" does not exist.")
        return 1
    elif (os.path.exists(args.output) and not os.path.isdir(args.output)):
        print(f"ERROR: File of the same name as the output folder found.")
        return 2

    img_width = -1
    img_height = -1

    os.makedirs(args.output, exist_ok=True)

    print(f"Reading {os.path.basename(args.input_file)}...")

    with open(args.input_file, "rb") as f:
        header = f.read(4).decode("ascii")
        if (header != "thba"):
            print(f"ERROR: The file specified is invalid and/or not a compressed video.")
            return 6
        
        # Skip fps
        f.read(1)
        has_compression = bool(int.from_bytes(f.read(1)))
        chunk_count = int.from_bytes(f.read(4))
        img_width = int.from_bytes(f.read(4))
        img_height = int.from_bytes(f.read(4))

        i = 0

        if (is_verbose):
            print(f"Chunk count: {chunk_count}")

        while (i < chunk_count):
            chunk_len = int.from_bytes(f.read(4))
            chunk_data = f.read(chunk_len)

            print(f"Decompressing chunk {i} / {chunk_count}")

            if (has_compression):
                chunk_data = lz4f.decompress(chunk_data)

            file_name = f"frame_{i+1:04d}.png"
            im = Image.frombytes("L", (img_width, img_height), chunk_data)

            print(f"Exporting {file_name}")

            im.save(os.path.join(args.output, file_name))
            i += 1

    return 0

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)