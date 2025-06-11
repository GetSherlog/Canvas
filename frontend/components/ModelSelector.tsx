"use client"

import { useState, useEffect } from "react"
import { Check, ChevronDown, Sparkles } from "lucide-react"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { api } from "@/api/client"
import type { Model } from "@/api/models"
import { useToast } from "@/hooks/use-toast"

interface ModelSelectorProps {
  onModelChange?: (model: Model) => void
}

export function ModelSelector({ onModelChange }: ModelSelectorProps) {
  const [models, setModels] = useState<Model[]>([])
  const [currentModel, setCurrentModel] = useState<Model | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [isChanging, setIsChanging] = useState(false)
  const { toast } = useToast()

  // Fetch models and current model on mount
  useEffect(() => {
    const fetchModels = async () => {
      try {
        setIsLoading(true)
        const [modelsList, current] = await Promise.all([api.models.listModels(), api.models.getCurrentModel()])
        setModels(modelsList)
        setCurrentModel(current)
      } catch (error) {
        console.error("Failed to fetch models:", error)
        toast({
          variant: "destructive",
        title: "Error",
        description: "Failed to load available models.",
      })
    } finally {
      setIsLoading(false)
    }
  }
    
    fetchModels()
  }, [toast])

  const handleModelSelect = async (model: Model) => {
    if (model.id === currentModel?.id) return

    try {
      setIsChanging(true)
      const updatedModel = await api.models.setCurrentModel(model.id)
      setCurrentModel(updatedModel)

      if (onModelChange) {
        onModelChange(updatedModel)
      }

      toast({
        title: "Model Changed",
        description: `Now using ${updatedModel.name}`,
      })
    } catch (error) {
      console.error("Failed to change model:", error)
      toast({
        variant: "destructive",
        title: "Error",
        description: "Failed to change the model. Please try again.",
      })
    } finally {
      setIsChanging(false)
    }
  }

  // Group models by provider
  const groupedModels = models.reduce(
    (acc, model) => {
      if (!acc[model.provider]) {
        acc[model.provider] = []
      }
      acc[model.provider].push(model)
      return acc
    },
    {} as Record<string, Model[]>,
  )

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="outline"
          size="sm"
          className="h-8 gap-1 border-purple-200 bg-purple-50 hover:bg-purple-100 text-purple-700"
          disabled={isLoading || isChanging}
        >
          <Sparkles className="h-3.5 w-3.5" />
          <span className="hidden sm:inline">{isLoading ? "Loading..." : currentModel?.name || "Select Model"}</span>
          <ChevronDown className="h-3.5 w-3.5 opacity-70" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-[240px] bg-white shadow-lg border border-gray-200">
        <DropdownMenuLabel>Select AI Model</DropdownMenuLabel>
        {Object.entries(groupedModels).map(([provider, providerModels]) => (
          <div key={provider}>
            <DropdownMenuSeparator />
            <DropdownMenuLabel className="text-xs text-muted-foreground">{provider}</DropdownMenuLabel>
            <DropdownMenuGroup>
              {providerModels.map((model) => (
                <DropdownMenuItem
                  key={model.id}
                  onClick={() => handleModelSelect(model)}
                  disabled={isChanging}
                  className="flex items-center justify-between cursor-pointer"
                >
                  <div className="flex flex-col">
                    <span>{model.name}</span>
                    {model.description && <span className="text-xs text-muted-foreground">{model.description}</span>}
                  </div>
                  {currentModel?.id === model.id && <Check className="h-4 w-4 text-green-600" />}
                </DropdownMenuItem>
              ))}
            </DropdownMenuGroup>
          </div>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
