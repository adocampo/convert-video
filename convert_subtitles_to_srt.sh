#!/bin/bash

archivo="$1"
nuevo_archivo="${archivo%.mkv}_corrected.mkv"

# Verificar si el archivo existe
if [[ ! -f "$archivo" ]]; then
    echo "El archivo no existe: $archivo"
    exit 1
fi

# Asegurar que usamos UTF-8 para el script
export LANG=es_ES.UTF-8
export LC_ALL=es_ES.UTF-8

# Obtener los IDs, los idiomas y los nombres de las pistas de subtítulos usando mkvmerge -J
metadata=$(mkvmerge -J "$archivo")

# Usar @csv para que jq escape correctamente los caracteres especiales
readarray -t tracks < <(echo "$metadata" | jq -r '.tracks[] | select(.type=="subtitles") | [.id, .properties.language, (.properties.track_name // "untitled")] | @csv')

ids=()
languages=()
names=()

for track in "${tracks[@]}"; do
    # Separar la línea CSV en campos, preservando caracteres especiales
    IFS=',' read -r id lang name <<< "$track"
    # Eliminar comillas dobles de los campos
    id=$(echo "$id" | tr -d '"')
    lang=$(echo "$lang" | tr -d '"')
    name=$(echo "$name" | tr -d '"')
    
    ids+=("$id")
    languages+=("$lang")
    names+=("$name")
done

# Mostrar los IDs, los idiomas y los nombres obtenidos
echo "IDs de pistas de subtítulos: ${ids[*]}"
echo "Idiomas de pistas de subtítulos: ${languages[*]}"
echo "Nombres de pistas de subtítulos: ${names[*]}"

# Crear un archivo temporal para almacenar las pistas de subtítulos
temp_files=()
srt_files=()

# Iterar sobre los IDs y extraer cada pista de subtítulos con su idioma y nombre
index=0
for id in "${ids[@]}"; do
    # Usar el índice para acceder a los arrays
    language="${languages[$index]}"
    name="${names[$index]}"
    # Sanitizar el nombre para usarlo en el nombre de archivo
    safe_name=$(echo "$name" | iconv -f utf-8 -t ascii//TRANSLIT | tr -cd '[:alnum:] -')
    
    output_file="subtitulos_${id}_${language}_${safe_name}.srt"
    mkvextract tracks "$archivo" "${id}:${output_file}"
    echo "Subtítulos extraídos: ${output_file}"
    
    # Convertir de ASS a SRT con ffmpeg si es un archivo ASS (se detecta por la cadena "[Script Info]")
    if grep -q "\[Script Info\]" "${output_file}"; then
        tmp_file="${output_file}.tmp.srt"
        ffmpeg -y -i "${output_file}" "${tmp_file}"
        if [[ $? -eq 0 ]]; then
            mv "${tmp_file}" "${output_file}"
            echo "Subtítulo convertido de ASS a SRT: ${output_file}"
        else
            echo "Error convirtiendo ${output_file} de ASS a SRT"
        fi
    fi

    # Eliminar etiquetas <font ...> y </font>, conservando el texto
    sed -i -E 's/<font[^>]*>//g; s/<\/font>//g' "${output_file}"
    echo "Etiquetas <font ...> y </font> eliminadas en: ${output_file}"
    
    # Convertir guiones a espacios en blanco para los metadatos
    name_with_spaces=$(echo "$name" | tr '-' ' ')
    
    # Crear un archivo temporal para cada pista de subtítulos
    temp_file="temp_sub_${id}.mkv"
    mkvmerge -o "$temp_file" --language 0:"$language" --track-name 0:"$name_with_spaces" "$output_file"
    temp_files+=("$temp_file")
    srt_files+=("$output_file")
    
    index=$((index + 1))
done

# Crear el nuevo archivo MKV con las pistas de audio, vídeo y los nuevos subtítulos
mkvmerge -o "$nuevo_archivo" --no-subtitles "$archivo" "${temp_files[@]}"

# Limpiar archivos temporales
rm "${temp_files[@]}"
rm "${srt_files[@]}"