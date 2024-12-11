#!/bin/bash

# Check if a file argument is provided
if [ $# -eq 0 ]; then
    echo "Error: No file provided"
    echo "Usage: $0 <filename>"
    exit 1
fi

# Get the full path of the input file
input_file=$(realpath "$1")

# Extract the filename without extension using mediainfo
filename=$(mediainfo --Inform="General;%FileName%" "$input_file")

# Update the title metadata
mkvpropedit "$input_file" --edit info --set "title=$filename"

echo "Metadata updated successfully for $input_file"

