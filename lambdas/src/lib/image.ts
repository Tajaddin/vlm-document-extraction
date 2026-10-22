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
