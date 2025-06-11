"use client"

import type React from "react"
import { Inter } from "next/font/google"
import "./globals.css"
import { ThemeProvider } from "@/components/theme-provider"
import { usePathname } from "next/navigation"
import StoreInitializer from "@/components/StoreInitializer"

// You can use Inter as a fallback, but we'll prioritize DM Sans from our CSS variables
const inter = Inter({ subsets: ["latin"], variable: "--font-inter" })

function RootLayoutContent({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()
  const isCanvasPage = pathname?.startsWith("/canvas/")

  return (
    <div className="min-h-screen flex flex-col">
      {!isCanvasPage && (
        <header className="border-b py-4 px-6 bg-background">
          <div className="container mx-auto">
            <h1 className="text-xl font-bold">Sherlog Canvas</h1>
          </div>
        </header>
      )}
      <main className={`flex-1 ${isCanvasPage ? "" : "container mx-auto py-6"}`}>{children}</main>
    </div>
  )
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        {/* Add Google Fonts for DM Sans, Lora, and IBM Plex Mono */}
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        {/* eslint-disable-next-line @next/next/no-page-custom-font */}
        <link
          href="https://fonts.googleapis.com/css2?family=DM+Sans:ital,wght@0,400;0,500;0,700;1,400&family=IBM+Plex+Mono:wght@400;500;600&family=Lora:ital,wght@0,400;0,500;0,600;0,700;1,400&display=swap"
          rel="stylesheet"
        />
      </head>
      <body className={inter.variable}>
        <ThemeProvider attribute="class" defaultTheme="light" enableSystem>
          <StoreInitializer />
          <RootLayoutContent>{children}</RootLayoutContent>
        </ThemeProvider>
      </body>
    </html>
  )
}
