import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "CTF — Creation to Transformation",
  description: "A human-led creation system grounded in evidence.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
