// SPDX-License-Identifier: GPL-3.0-only
// Test-only snapshot of the ComfyUI frontend PNG decoder.
// Source: https://github.com/Comfy-Org/ComfyUI_frontend/blob/f288d755b488f8bf6609100ee3e8c8b507d88630/src/scripts/metadata/png.ts
// Original source SHA-256: f48fd6b5014f59c48ebdf0d94d168655fae30a5f45da5e17c25e0c03469750df
// TypeScript types erased with node:module stripTypeScriptTypes; logic unchanged.
// License: LICENSE.ComfyUI_frontend in this directory.

async function decompressZlib(
  data                         
)                                   {
  const stream = new DecompressionStream('deflate')
  const writer = stream.writable.getWriter()
  try {
    await writer.write(data)
    await writer.close()
  } finally {
    writer.releaseLock()
  }

  const reader = stream.readable.getReader()
  const chunks                            = []
  let totalLength = 0

  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      chunks.push(value)
      totalLength += value.length
    }
  } finally {
    reader.releaseLock()
  }

  const result = new Uint8Array(totalLength)
  let offset = 0
  for (const chunk of chunks) {
    result.set(chunk, offset)
    offset += chunk.length
  }
  return result
}

export async function getFromPngBuffer(
  buffer             
)                                  {
  const pngData = new Uint8Array(buffer)
  const dataView = new DataView(pngData.buffer)

  if (dataView.getUint32(0) !== 0x89504e47) {
    console.error('Not a valid PNG file')
    return {}
  }

  let offset = 8
  const txt_chunks                         = {}

  while (offset < pngData.length) {
    const length = dataView.getUint32(offset)
    const type = String.fromCharCode(...pngData.slice(offset + 4, offset + 8))

    if (type === 'tEXt' || type === 'comf' || type === 'iTXt') {
      let keyword_end = offset + 8
      while (pngData[keyword_end] !== 0) {
        keyword_end++
      }
      const keyword = String.fromCharCode(
        ...pngData.slice(offset + 8, keyword_end)
      )

      let textStart = keyword_end + 1
      let isCompressed = false
      let compressionMethod = 0

      if (type === 'iTXt') {
        const chunkEnd = offset + 8 + length
        isCompressed = pngData[textStart] === 1
        compressionMethod = pngData[textStart + 1]
        textStart += 2

        while (pngData[textStart] !== 0 && textStart < chunkEnd) {
          textStart++
        }
        if (textStart < chunkEnd) textStart++

        while (pngData[textStart] !== 0 && textStart < chunkEnd) {
          textStart++
        }
        if (textStart < chunkEnd) textStart++
      }

      let contentArraySegment = pngData.slice(textStart, offset + 8 + length)

      if (isCompressed) {
        if (compressionMethod === 0) {
          try {
            contentArraySegment = await decompressZlib(contentArraySegment)
          } catch (e) {
            console.error(`Failed to decompress iTXt chunk "${keyword}":`, e)
            offset += 12 + length
            continue
          }
        } else {
          console.warn(
            `Unsupported compression method ${compressionMethod} for iTXt chunk "${keyword}"`
          )
          offset += 12 + length
          continue
        }
      }

      const contentJson = new TextDecoder('utf-8').decode(contentArraySegment)
      txt_chunks[keyword] = contentJson
    }

    offset += 12 + length
  }
  return txt_chunks
}

export async function getFromPngFile(
  file      
)                                  {
  return new Promise                        ((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = async (event) => {
      const buffer = event.target?.result
      if (!(buffer instanceof ArrayBuffer)) {
        reject(new Error('Failed to read file as ArrayBuffer'))
        return
      }
      const result = await getFromPngBuffer(buffer)
      resolve(result)
    }
    reader.onerror = () => reject(reader.error)
    reader.onabort = () => reject(new Error('FileReader aborted'))
    reader.readAsArrayBuffer(file)
  })
}
