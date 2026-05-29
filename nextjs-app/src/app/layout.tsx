import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Agent Auth with JWT — POC",
  description: "SSO-protected OpenCode with FastMCP JWT authentication",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
