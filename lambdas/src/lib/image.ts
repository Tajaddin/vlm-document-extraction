// Accept only the image types the extractors read, and check the bytes, not just the header the client sent.

export type ImageType = "image/jpeg" | "image/png";

export const EXTENSIONS: Record<ImageType, string> = { "image/jpeg": "jpg", "image/png": "png" };

export function isImageType(value: string): value is ImageType {
  return value === "image/jpeg" || value === "image/png";
}

/** The type the file's first bytes say it is, or undefined. */
export function sniff(bytes: Uint8Array): ImageType | undefined {
  if (bytes.length >= 3 && bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff) return "image/jpeg";
  const png = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a];
  if (bytes.length >= png.length && png.every((b, i) => bytes[i] === b)) return "image/png";
  return undefined;
}

/**
 * Width times height as the header states it (the PNG IHDR chunk, the JPEG start-of-frame segment), read without
 * decoding anything; undefined when the header does not give a size. A few kilobytes can declare a picture that
 * takes gigabytes to decode, so the size limit on the bytes alone does not bound the worker's memory.
 */
export function pixels(bytes: Uint8Array, type: ImageType): number | undefined {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  if (type === "image/png") {
    const ihdr = bytes.length >= 24 && view.getUint32(12) === 0x49484452;
    return ihdr ? positive(view.getUint32(16) * view.getUint32(20)) : undefined;
  }
  let at = 2; // after the start-of-image marker
  while (at + 4 <= bytes.length) {
    if (bytes[at] !== 0xff) return undefined;
    const marker = view.getUint8(at + 1);
    if (marker === 0xff) {
      at += 1; // fill byte
    } else if (marker === 0x01 || (marker >= 0xd0 && marker <= 0xd7)) {
      at += 2; // markers without a segment
    } else if (marker >= 0xc0 && marker <= 0xcf && marker !== 0xc4 && marker !== 0xc8 && marker !== 0xcc) {
      return at + 9 <= bytes.length ? positive(view.getUint16(at + 5) * view.getUint16(at + 7)) : undefined;
    } else if (marker === 0xd9 || marker === 0xda) {
      return undefined; // end of image, or the scan, before any frame header
    } else {
      at += 2 + view.getUint16(at + 2);
    }
  }
  return undefined;
}

function positive(n: number): number | undefined {
  return n > 0 ? n : undefined;
}
