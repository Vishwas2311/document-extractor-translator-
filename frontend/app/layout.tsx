import type { Metadata } from "next";
import { headers } from "next/headers";
import "./globals.css";

export async function generateMetadata(): Promise<Metadata> {
  const requestHeaders = await headers();
  const rawHost = requestHeaders.get("x-forwarded-host") ?? requestHeaders.get("host") ?? "localhost:3000";
  const host = /^[a-z0-9.:-]+$/i.test(rawHost) ? rawHost : "localhost:3000";
  const protocol = requestHeaders.get("x-forwarded-proto") ?? (host.startsWith("localhost") ? "http" : "https");
  const origin = protocol + "://" + host;
  const previewImage = origin + "/caretranslate-social.png";

  return {
    metadataBase: new URL(origin),
    title: "CareTranslate Studio | Youth Care Document Intelligence",
    description: "Extract and translate Arabic and Mandarin youth-care documents into reviewable, page-wise English JSON.",
    icons: {
      icon: "/favicon.svg",
      shortcut: "/favicon.svg",
    },
    openGraph: {
      title: "CareTranslate Studio",
      description: "Arabic and Mandarin document extraction, English translation, and page-wise structured review.",
      images: [{ url: previewImage, width: 1536, height: 1024, alt: "CareTranslate Studio document review workflow" }],
      type: "website",
    },
    twitter: {
      card: "summary_large_image",
      title: "CareTranslate Studio",
      description: "Multilingual document intelligence for youth-care teams.",
      images: [previewImage],
    },
  };
}

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
