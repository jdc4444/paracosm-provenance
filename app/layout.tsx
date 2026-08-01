import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { headers } from "next/headers";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

const description =
  "The source, camera, asset, feedback, and visual mockup library for the Paracosm short film.";

export async function generateMetadata(): Promise<Metadata> {
  const requestHeaders = await headers();
  const host =
    requestHeaders.get("x-forwarded-host") || requestHeaders.get("host");
  const protocol =
    requestHeaders.get("x-forwarded-proto") ||
    (host?.startsWith("localhost") ? "http" : "https");
  const socialImage = host ? `${protocol}://${host}/og.png` : "/og.png";

  return {
    title: "Paracosm",
    description,
    openGraph: {
      title: "Paracosm · Mockup Library",
      description,
      type: "website",
      images: [
        {
          url: socialImage,
          width: 1200,
          height: 630,
          alt: "Paracosm Blue Steel Mockup Library · Pass 01 · TH",
        },
      ],
    },
    twitter: {
      card: "summary_large_image",
      title: "Paracosm · Mockup Library",
      description,
      images: [socialImage],
    },
  };
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="theme-light">
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased`}
      >
        {children}
      </body>
    </html>
  );
}
