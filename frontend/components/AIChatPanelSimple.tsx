"use client"

import type React from "react"
import { useState, useEffect, useRef, useCallback } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Send, Bot, User, Loader2, AlertCircle, RefreshCw, Paperclip } from "lucide-react"
import { chatAPI, type ChatMessage } from "@/api/chatSimple"
import { useToast } from "@/hooks/use-toast"
import { Alert, AlertDescription } from "@/components/ui/alert"

// Import the simplified hook
import { useInvestigationEventsSimple } from "@/hooks/useInvestigationEventsSimple"

interface AIChatPanelProps {
  isOpen: boolean
  onToggle: () => void
  notebookId: string
}

export default function AIChatPanel({ isOpen, notebookId }: AIChatPanelProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState("")
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [lastFailedMessage, setLastFailedMessage] = useState<string | null>(null)
  const [isRetrying, setIsRetrying] = useState(false)
  const [selectedFile, setSelectedFile] = useState<File | null>(null)

  const { toast } = useToast()
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  // Use the simplified investigation events hook
  const { isInvestigationRunning, currentStatus, wsStatus } = useInvestigationEventsSimple(notebookId)

  // Create a new chat session
  const createChatSession = useCallback(async () => {
    try {
      setIsLoading(true)
      setError(null)

      const session = await chatAPI.createSession(notebookId)
      setSessionId(session.session_id)

      // Load existing messages if any
      if (session.session_id) {
        const existingMessages = await chatAPI.getSessionMessages(session.session_id)
        if (existingMessages.length > 0) {
          setMessages(existingMessages)
        }
      }
    } catch (err) {
      console.error("Failed to create chat session:", err)
      setError("Failed to create chat session. Please try again.")
      toast({
        variant: "destructive",
        title: "Session Error",
        description: "Failed to create chat session.",
      })
    } finally {
      setIsLoading(false)
    }
  }, [notebookId, toast])

  // Create chat session when panel opens
  useEffect(() => {
    if (isOpen && !sessionId) {
      createChatSession()
    }
  }, [isOpen, sessionId, createChatSession])

  // Focus input when panel opens
  useEffect(() => {
    if (isOpen && inputRef.current) {
      inputRef.current.focus()
    }
  }, [isOpen])

  // Scroll to bottom when messages change
  useEffect(() => {
    if (messagesEndRef.current) {
      messagesEndRef.current.scrollIntoView({ behavior: "smooth" })
    }
  }, [messages])

  // Handle sending a message
  const handleSendMessage = async () => {
    if (!input.trim() && !selectedFile) return
    if (isLoading || !sessionId) return

    const messageToSend = input.trim()
    setInput("")
    setError(null)
    setIsLoading(true)
    setLastFailedMessage(messageToSend)

    // Add user message to the chat immediately
    const userMessage: ChatMessage = {
      role: "user",
      content: messageToSend,
      timestamp: new Date().toISOString(),
    }
    setMessages((prev) => [...prev, userMessage])

    try {
      // Send message to API and handle streaming response
      let assistantMessage: ChatMessage | null = null
      
      for await (const message of chatAPI.sendMessage(sessionId, messageToSend)) {
        if (message.role === "assistant") {
          // For assistant messages, update the existing message or create a new one
          if (!assistantMessage || message.agent !== assistantMessage.agent) {
            // New agent response, add as new message
            assistantMessage = message
            setMessages((prev) => [...prev, message])
          } else {
            // Same agent, update the content of the last message
            setMessages((prev) => {
              const newMessages = [...prev]
              const lastIndex = newMessages.length - 1
              if (lastIndex >= 0 && newMessages[lastIndex].role === "assistant") {
                // Append content to the existing message
                newMessages[lastIndex] = {
                  ...newMessages[lastIndex],
                  content: newMessages[lastIndex].content + message.content
                }
              }
              return newMessages
            })
          }
        } else {
          // For status/error messages, always add as new
          setMessages((prev) => [...prev, message])
        }
      }

      // Clear the failed message after successful send
      setLastFailedMessage(null)
    } catch (error) {
      console.error("Error sending message:", error)
      
      const errorMessage = error instanceof Error ? error.message : "Failed to send message"
      setError(errorMessage)

      toast({
        variant: "destructive",
        title: "Chat Error",
        description: errorMessage,
      })
    } finally {
      setIsLoading(false)
    }
  }

  // Handle retrying a failed message
  const handleRetry = async () => {
    if (!lastFailedMessage || isLoading || !sessionId) return

    setIsRetrying(true)
    setError(null)
    
    // Reuse the send message logic
    setInput(lastFailedMessage)
    await handleSendMessage()
    
    setIsRetrying(false)
  }

  // Handle file selection
  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file) {
      setSelectedFile(file)
      // TODO: Implement file upload
      toast({
        title: "File selected",
        description: `Selected: ${file.name}`,
      })
    }
  }

  // Render a single message
  const renderMessage = (message: ChatMessage, index: number) => {
    const isUser = message.role === "user"
    const isStatus = message.role === "status"
    const isError = message.role === "error"

    if (isStatus) {
      return (
        <div key={index} className="flex items-center gap-2 text-sm text-gray-500 px-4 py-2">
          <div className="animate-pulse w-2 h-2 bg-blue-500 rounded-full" />
          {message.content}
        </div>
      )
    }

    return (
      <div
        key={index}
        className={`flex gap-3 px-4 py-3 ${
          isUser ? "bg-gray-50 dark:bg-gray-800" : "bg-white dark:bg-gray-900"
        } ${isError ? "border-l-4 border-red-500" : ""}`}
      >
        <div className="flex-shrink-0">
          {isUser ? (
            <div className="w-8 h-8 bg-blue-600 rounded-full flex items-center justify-center">
              <User className="h-4 w-4 text-white" />
            </div>
          ) : (
            <div className={`w-8 h-8 ${isError ? "bg-red-600" : "bg-purple-600"} rounded-full flex items-center justify-center`}>
              {isError ? <AlertCircle className="h-4 w-4 text-white" /> : <Bot className="h-4 w-4 text-white" />}
            </div>
          )}
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-sm font-medium text-gray-900 dark:text-gray-100 mb-1">
            {isUser ? "You" : isError ? "Error" : message.agent || "Assistant"}
          </div>
          <div className="text-sm text-gray-700 dark:text-gray-300 whitespace-pre-wrap break-words">
            {message.content}
          </div>
        </div>
      </div>
    )
  }

  if (!isOpen) return null

  return (
    <div className="fixed bottom-0 right-0 w-[420px] h-[600px] bg-white dark:bg-gray-900 shadow-xl rounded-tl-lg rounded-tr-lg border-l border-t border-gray-200 dark:border-gray-700 flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200 dark:border-gray-700">
        <div className="flex items-center gap-2">
          <Bot className="h-5 w-5 text-purple-600" />
          <h3 className="font-semibold text-gray-900 dark:text-gray-100">AI Assistant</h3>
        </div>
        <div className="flex items-center gap-2">
          {wsStatus === "connected" && (
            <div className="flex items-center gap-1">
              <div className="w-2 h-2 bg-green-500 rounded-full" />
              <span className="text-xs text-gray-500">Connected</span>
            </div>
          )}
          {isInvestigationRunning && (
            <div className="flex items-center gap-1">
              <Loader2 className="h-3 w-3 animate-spin text-purple-600" />
              <span className="text-xs text-purple-600">Investigating...</span>
            </div>
          )}
        </div>
      </div>

      {/* Current Status */}
      {currentStatus && (
        <div className="px-4 py-2 bg-blue-50 dark:bg-blue-900/20 border-b border-blue-200 dark:border-blue-800">
          <p className="text-sm text-blue-700 dark:text-blue-300">{currentStatus}</p>
        </div>
      )}

      {/* Messages */}
      <div className="flex-1 overflow-y-auto">
        {messages.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-gray-500 p-8">
            <Bot className="h-12 w-12 mb-4 text-gray-400" />
            <p className="text-center">
              Ask me anything about your investigation. I can help analyze code, logs, and more.
            </p>
          </div>
        ) : (
          <div className="space-y-0">
            {messages.map((message, index) => renderMessage(message, index))}
            <div ref={messagesEndRef} />
          </div>
        )}
      </div>

      {/* Error Alert */}
      {error && (
        <Alert variant="destructive" className="mx-4 mb-4">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription className="flex items-center justify-between">
            <span>{error}</span>
            {lastFailedMessage && (
              <Button
                variant="ghost"
                size="sm"
                onClick={handleRetry}
                disabled={isRetrying}
                className="ml-2"
              >
                {isRetrying ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />}
              </Button>
            )}
          </AlertDescription>
        </Alert>
      )}

      {/* Input */}
      <div className="border-t border-gray-200 dark:border-gray-700 p-4">
        <div className="flex gap-2">
          <Button
            variant="ghost"
            size="icon"
            onClick={() => fileInputRef.current?.click()}
            disabled={isLoading}
          >
            <Paperclip className="h-4 w-4" />
          </Button>
          <Input
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && handleSendMessage()}
            placeholder="Type your message..."
            disabled={isLoading || !sessionId}
            className="flex-1"
          />
          <Button onClick={handleSendMessage} disabled={isLoading || !sessionId || (!input.trim() && !selectedFile)}>
            {isLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
          </Button>
        </div>
        {selectedFile && (
          <div className="mt-2 text-sm text-gray-600 flex items-center gap-2">
            <Paperclip className="h-3 w-3" />
            {selectedFile.name}
          </div>
        )}
      </div>

      {/* Hidden file input */}
      <input
        ref={fileInputRef}
        type="file"
        onChange={handleFileSelect}
        className="hidden"
        accept="image/*,.pdf,.txt,.md,.log"
      />
    </div>
  )
}