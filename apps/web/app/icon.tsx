import { ImageResponse } from "next/og";

export const size = {
  width: 64,
  height: 64,
};

export const contentType = "image/png";

export default function Icon() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "#02060d",
          color: "#e2e8f0",
          fontSize: 44,
          fontWeight: 800,
          fontFamily: "Arial, sans-serif",
          border: "1px solid #1f2f45",
        }}
      >
        I
      </div>
    ),
    {
      ...size,
    }
  );
}
