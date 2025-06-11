"use client"

import { Button } from "@/components/ui/button"
import { Bot } from "lucide-react"

interface AIChatToggleProps {
  isOpen: boolean
  onToggle: () => void
}

export default function AIChatToggle({ isOpen, onToggle }: AIChatToggleProps) {
  // If the panel is open, we don't need to show this button
  if (isOpen) {
    return null
  }

  return (
    <Button
      onClick={onToggle}
      className="fixed right-6 bottom-6 rounded-full shadow-lg z-30 transition-all duration-300 bg-purple-600 text-white hover:bg-purple-700 hover:shadow-xl px-4 py-3 h-auto"
    >
      <Bot className="h-5 w-5 mr-2" />
      <span className="font-medium">Ask Sherlog</span>
    </Button>
  )
}
