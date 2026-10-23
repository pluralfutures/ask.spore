import { encodeQr, qrPath } from "../lib/qr";

// P1c-08: a QR code drawn in the browser from text (the TOTP enrolment URI); no image
// request, no third-party service, no new dependency.
export function QrCode({ text, label }: { text: string; label: string }) {
  let path: { d: string; size: number };
  try {
    path = qrPath(encodeQr(text));
  } catch {
    return null; // too long for a QR code: the key below is still there to type
  }
  return (
    <svg
      role="img"
      aria-label={label}
      viewBox={`0 0 ${path.size} ${path.size}`}
      width={path.size * 5}
      height={path.size * 5}
      shapeRendering="crispEdges"
      className="self-center"
    >
      <rect width={path.size} height={path.size} fill="#fff" />
      <path d={path.d} fill="#000" />
    </svg>
  );
}
