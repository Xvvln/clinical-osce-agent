import type { Metadata } from "next";
import type { ReactNode } from "react";
import "./globals.css";

export const metadata: Metadata = {
  title: "临境 OSCE 智能体（TraceOSCE）管理后台",
  description: "临境 OSCE 智能体（TraceOSCE）的教师与管理端复盘后台",
  icons: { icon: "/admin-icon.svg" },
};

type RootLayoutProps = Readonly<{
  children: ReactNode;
}>;

export default function RootLayout({ children }: RootLayoutProps) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
