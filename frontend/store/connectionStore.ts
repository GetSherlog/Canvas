import { create } from "zustand"
import { devtools, persist } from "zustand/middleware"
import type { Connection } from "./types"
import { api } from "../api/client"
import type { MCPToolInfo } from "./types"

interface ConnectionState {
  // Connection data
  connections: Connection[]
  availableTypes: string[]

  // Tool definitions per connection type
  toolDefinitions: Record<string, MCPToolInfo[] | undefined>
  toolLoadingStatus: Record<string, 'idle' | 'loading' | 'success' | 'error'>

  // MCP Statuses per connection ID
  mcpStatuses: Record<string, { status: string; message?: string } | undefined>

  // Loading states
  loading: boolean
  error: string | null

  // Global UI states
  areAllCellsExpanded: boolean

  // Actions
  loadConnections: () => Promise<void>
  loadAvailableTypes: () => Promise<void>
  createConnection: (connectionData: Partial<Connection>) => Promise<Connection | null>
  updateConnection: (id: string, connectionData: Partial<Connection>) => Promise<Connection | null>
  deleteConnection: (id: string) => Promise<boolean>
  setDefaultConnection: (id: string) => Promise<boolean>
  testConnection: (connectionData: Partial<Connection>) => Promise<{ valid: boolean; message: string }>
  fetchToolsForConnection: (connectionType: string) => Promise<void>
  toggleAllCellsExpanded: () => void
  reindexConnection: (connectionId: string) => Promise<{ message: string }>

  // Utility
  getConnectionsByType: (type: string) => Connection[]
  getDefaultConnection: (type: string) => Connection | null
}

export const useConnectionStore = create<ConnectionState>()(
  devtools(
    persist(
      (set, get) => ({
        // Initial state
        connections: [],
        loading: false,
        error: null,
        toolDefinitions: {},
        toolLoadingStatus: {},
        mcpStatuses: {}, // Initialize mcpStatuses
        availableTypes: [],
        areAllCellsExpanded: false,

        // Toggle all cells expanded state
        toggleAllCellsExpanded: () => {
          set((state) => ({ areAllCellsExpanded: !state.areAllCellsExpanded }))
        },

        // Load all connections
        loadConnections: async () => {
          console.log("useConnectionStore: loadConnections called")
          set({ loading: true, error: null })
          
          // Call loadAvailableTypes concurrently or sequentially?
          // Let's call it concurrently for efficiency
          const loadTypesPromise = get().loadAvailableTypes();

          try {
            // Assume api.connections.list() returns Connection[] as typed
            const connectionsFromApi = await api.connections.list()

            // Ensure connectionsFromApi is actually an array before proceeding
            if (!Array.isArray(connectionsFromApi)) {
              console.error("API response for connections is not an array:", connectionsFromApi)
              throw new Error("Invalid data received from server.") // Trigger the catch block
            }

            // Ensure each connection has the is_default field (default to false)
            const connections = connectionsFromApi.map(conn => ({
              ...conn,
              is_default: conn.is_default ?? false,
            }))

            // The type system should handle if the response isn't Connection[]
            // Explicitly assert the type to match the state definition
            set({ connections: connections as Connection[], loading: false })

            // After loading connections, fetch tools for each unique type found
            const connectionTypes = [...new Set(connections.map(conn => conn.type))];
            connectionTypes.forEach(type => {
              // Don't re-fetch if already loading or loaded
              if (!get().toolLoadingStatus[type] || get().toolLoadingStatus[type] === 'idle' || get().toolLoadingStatus[type] === 'error') {
                 get().fetchToolsForConnection(type);
              }
            });

            // Explicitly ensure Python tools are loaded if they haven't been attempted yet
            const pythonToolStatus = get().toolLoadingStatus['python'];
            if (!pythonToolStatus || pythonToolStatus === 'idle' || pythonToolStatus === 'error') {
                console.log("Explicitly fetching tools for 'python' type.");
                get().fetchToolsForConnection('python');
            }

            // Wait for types to load as well (if needed before proceeding)
            // or just let it run in background if types aren't needed immediately after loadConnections
            // await loadTypesPromise; // Uncomment if subsequent logic depends on types being loaded

          } catch (err) {
            console.error("Failed to load connections:", err)
            set({
              error: "Failed to load connections. Please try again.",
              loading: false,
              connections: [], // Ensure connections is reset on error
            })
            // Ensure the types promise doesn't cause unhandled rejection if it also fails
            loadTypesPromise.catch(typeErr => console.error("Error from concurrent loadAvailableTypes:", typeErr));
          }
        },

        // Load available connection types
        loadAvailableTypes: async () => {
          try {
            // Avoid re-fetching if already populated? Or always refresh?
            // Let's refresh for now, could add a check later.
            const types = await api.connections.getTypes();
            set({ availableTypes: types });
          } catch (err) {
            console.error("Failed to load available connection types:", err);
            // Set error state or show toast?
            // For now, just log and leave types empty/stale
            set(state => ({ 
              error: state.error || "Failed to load connection types."
            })); 
          }
        },

        // Create a new connection
        createConnection: async (connectionData: Partial<Connection>) => {
          try {
            console.log("useConnectionStore: Calling unified api.connections.create");
            // Check for required fields before calling API
            if (!connectionData.name || !connectionData.type) {
              throw new Error("Connection name and type are required to create.");
            }

            // Destructure name, type, and config from the input
            const { name, type, config, ...rest } = connectionData;

            // Prepare data for the API client, spreading the config object
            const dataForApi = {
              name,
              type,
              ...(config || {}), // Spread the contents of config
              ...rest // Include any other top-level fields if necessary
            };

            // Use type assertion after checks
            const newConnection = await api.connections.create(dataForApi as { name: string; type: string; [key: string]: any });

            // Only update state if creation was successful (newConnection should not be null from the unified API)
            if (newConnection) {
              set((state) => ({
                connections: [...state.connections, newConnection as Connection],
              }))
              // Fetch tools for the new connection type if not already loaded/loading
              const currentToolStatus = get().toolLoadingStatus[newConnection.type];
              if (!currentToolStatus || currentToolStatus === 'idle' || currentToolStatus === 'error') {
                get().fetchToolsForConnection(newConnection.type);
              }
              return newConnection // Return the created connection
            } else {
              // This case should technically not be reached if api.connections.create throws on failure
              console.error("useConnectionStore: api.connections.create returned nullish value unexpectedly.");
              throw new Error("Connection creation failed unexpectedly.")
            }
          } catch (err) {
            console.error("useConnectionStore: Failed to create connection:", err)
            // Propagate the error message for the UI to display
            if (err instanceof Error) {
                throw err;
            }
            throw new Error("An unknown error occurred while creating the connection.")
          }
        },

        // Update an existing connection
        updateConnection: async (id, connectionData) => {
          try {
             // Check for required type field before calling API
            if (!connectionData.type) {
              // This shouldn't happen if updating an existing connection, but check defensively
              throw new Error("Connection type is required for update.");
            }
            // Use type assertion after check
            const updatedConnection = await api.connections.update(id, connectionData as { name?: string; type: string; [key: string]: any });
            set((state) => ({
              connections: state.connections.map((conn) => (conn.id === id ? updatedConnection : conn)),
            }))
    return updatedConnection
  } catch (err) {
    console.error("useConnectionStore: Failed to update connection:", err)
    // Propagate the error message for the UI to display
    if (err instanceof Error) {
        throw err;
    }
    throw new Error("An unknown error occurred while updating the connection.")
  }
},

        // Delete a connection
        deleteConnection: async (id) => {
          try {
            await api.connections.delete(id)
            set((state) => ({
              connections: state.connections.filter((conn) => conn.id !== id),
            }))
            return true
          } catch (err) {
            console.error("Failed to delete connection:", err)
            return false
          }
        },

        // Set a connection as default
        setDefaultConnection: async (id) => {
          try {
            await api.connections.setDefault(id)
            set((state) => ({
              connections: state.connections.map((conn) => ({
                ...conn,
                is_default: conn.id === id,
              })),
            }))
            return true
          } catch (err) {
            console.error("Failed to set default connection:", err)
            return false
          }
        },

        // Test a connection
        testConnection: async (connectionData) => {
          try {
            // Ensure the connection type is present before calling the API
            if (!connectionData.type) {
               throw new Error("Connection type is required for testing.");
            }
            // Cast connectionData to the expected type after the check
            // The rest operator (...) correctly includes other fields
            return await api.connections.test(connectionData as { type: string; [key: string]: any }); 
          } catch (err) {
            console.error("Failed to test connection:", err)
            // Return the correct structure on error
            const message = err instanceof Error ? err.message : "Failed to test connection"
            return { valid: false, message }
          }
        },

        // Fetch tools for a specific connection type
        fetchToolsForConnection: async (connectionType) => {
          console.log(`useConnectionStore: fetchToolsForConnection called for ${connectionType}`);
          const currentStatus = get().toolLoadingStatus[connectionType];
          // Avoid redundant fetches
          if (currentStatus === 'loading' || currentStatus === 'success') {
            console.log(`Skipping fetch for ${connectionType}, status: ${currentStatus}`);
            return;
          }

          set(state => ({
            toolLoadingStatus: { ...state.toolLoadingStatus, [connectionType]: 'loading' },
          }));

          try {
            console.log(`useConnectionStore: Attempting to fetch tools for ${connectionType}...`);
            const tools = await api.connections.getTools(connectionType);
            console.log(`useConnectionStore: Received tools for ${connectionType}:`, tools);
            set(state => {
              console.log(`useConnectionStore: Setting definitions and status=success for ${connectionType}`);
              return {
                toolDefinitions: { ...state.toolDefinitions, [connectionType]: tools },
                toolLoadingStatus: { ...state.toolLoadingStatus, [connectionType]: 'success' },
              }
            });
          } catch (err) {
            console.error(`Failed to fetch tools for ${connectionType}:`, err);
            set(state => {
              console.log(`useConnectionStore: Setting status=error for ${connectionType}`);
              return {
                 toolLoadingStatus: { ...state.toolLoadingStatus, [connectionType]: 'error' },
                // Optionally clear definitions on error, or keep stale data
                // toolDefinitions: { ...state.toolDefinitions, [connectionType]: undefined }, 
              }
            });
          }
        },

        // Get connections by type
        getConnectionsByType: (type) => {
          return get().connections.filter((conn) => conn.type === type)
        },

        // Get default connection by type
        getDefaultConnection: (type) => {
          const connections = get().getConnectionsByType(type)
          return connections.find((conn) => conn.is_default) || connections[0] || null
        },

        // Reindex a connection
        reindexConnection: async (connectionId) => {
          // Set loading state? Maybe specific reindexing state?
          // set(state => ({ ... }))
          try {
            const result = await api.connections.reindex(connectionId); // result is { message: string }
            // Optionally update some state here if needed
            return result; // Return { message: string } directly
          } catch (err) {
            console.error("Failed to reindex connection:", err);
            // Re-throw the error for the UI to handle
            if (err instanceof Error) {
                throw err; // Throw error caught by API client (includes backend message)
            }
            throw new Error("An unknown error occurred during re-indexing.");
          } finally {
            // Reset loading state?
            // set(state => ({ ... }))
          }
        },
      }),
      {
        name: "connection-store",
        partialize: (state) => ({}), // Don't persist any state
      },
    ),
  ),
)
