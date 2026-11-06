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
 *
 * The header is read up to the image data and must state exactly one size: PIL keeps the last IHDR or frame header it
 * meets, so a small one in front of a large one would otherwise pass. Anything in a JPEG header that is not a
 * segment with a length (PIL and Go's decoder skip some markers as two bytes) is refused rather than guessed at.
 */
export function pixels(bytes: Uint8Array, type: ImageType): number | undefined {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  return type === "image/png" ? pngPixels(bytes, view) : jpegPixels(bytes, view);
}

const IHDR = 0x49484452;
const IDAT = 0x49444154;

function pngPixels(bytes: Uint8Array, view: DataView): number | undefined {
  // the signature, then the IHDR chunk, which comes first and holds 13 bytes
  if (bytes.length < 33 || view.getUint32(8) !== 13 || view.getUint32(12) !== IHDR) return undefined;
  const size = view.getUint32(16) * view.getUint32(20);
  for (let at = 33; at + 8 <= bytes.length; at += 12 + view.getUint32(at)) {
    const chunk = view.getUint32(at + 4);
    if (chunk === IDAT) return positive(size);
    if (chunk === IHDR) return undefined;
  }
  return undefined;
}

// start of frame, every coding process; 0xc4, 0xc8 and 0xcc in that range are other markers
const FRAMES = new Set([0xc0, 0xc1, 0xc2, 0xc3, 0xc5, 0xc6, 0xc7, 0xc9, 0xca, 0xcb, 0xcd, 0xce, 0xcf]);

/** Segments a header holds before its scan, each skipped by its length: tables, restart interval, APPn, comment. */
function isSegment(marker: number): boolean {
  return FRAMES.has(marker) || [0xc4, 0xcc, 0xdb, 0xdd, 0xfe].includes(marker) || (marker >= 0xe0 && marker <= 0xef);
}

function jpegPixels(bytes: Uint8Array, view: DataView): number | undefined {
  let size: number | undefined;
  let at = 2; // after the start-of-image marker
  while (at + 2 <= bytes.length) {
    if (bytes[at] !== 0xff) return undefined;
    const marker = view.getUint8(at + 1);
    if (marker === 0xff) {
      at += 1; // fill byte
      continue;
    }
    if (marker === 0xda) return positive(size); // start of scan: the image data
    if (!isSegment(marker) || at + 4 > bytes.length) return undefined;
    const length = view.getUint16(at + 2);
    if (length < 2) return undefined;
    if (FRAMES.has(marker)) {
      if (size !== undefined || length < 8 || at + 9 > bytes.length) return undefined;
      size = view.getUint16(at + 5) * view.getUint16(at + 7);
    }
    at += 2 + length;
  }
  return undefined;
}

function positive(n: number | undefined): number | undefined {
  return n !== undefined && n > 0 ? n : undefined;
}
