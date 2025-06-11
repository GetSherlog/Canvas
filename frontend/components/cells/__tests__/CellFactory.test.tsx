import React from 'react'
import { render, screen } from '@testing-library/react'
import CellFactory from '../CellFactory'
import type { Cell, CellType } from '../../../store/types' // Adjusted path

// Mock next/dynamic
jest.mock('next/dynamic', () => ({
  __esModule: true,
  default: (loader: () => Promise<{ default: React.ComponentType<unknown> }>) => {
    // In a test environment, we can resolve the dynamic import immediately
    // or return a mock. For simplicity, let's try to load it.
    // This might still require the loader to be a function that returns a module with a default export.
    let LoadedComponent: React.ComponentType<unknown> | null = null;
    try {
      // This is a bit of a hack and might not always work depending on how Jest handles the import()
      // A more robust solution might involve specific mocks for each dynamic component path.
      const dynamicImport = loader();
      dynamicImport.then((mod) => {
        LoadedComponent = mod.default;
      }).catch(() => {
        // Fallback or error
      });
    } catch {
      // Fallback
    }
    // Return a component that tries to render the loaded one, or a placeholder
    return (props: unknown) => {
      if (LoadedComponent) {
        return <LoadedComponent {...props} />;
      }
      // Fallback if direct loading in mock fails, rely on individual mocks below.
      // This part might be tricky. The individual mocks below should take precedence if this fails.
      return <div data-testid="dynamic-loading-fallback">Loading...</div>;
    };
  },
}));


// Mock individual cell components
// It's better to import the mocked components to access their .mock property
import MarkdownCellMock from '../MarkdownCell';
import ToolCellMock from '../ToolCell';

jest.mock('../MarkdownCell', () => ({
  __esModule: true,
  default: jest.fn((props) => <div data-testid="markdown-cell" data-props={JSON.stringify(props)} />),
}));
jest.mock('../ToolCell', () => ({
  __esModule: true,
  default: jest.fn((props) => <div data-testid="tool-cell" data-props={JSON.stringify(props)} />),
}));


describe('CellFactory', () => {
  const mockOnExecute = jest.fn()
  const mockOnUpdate = jest.fn()
  const mockOnDelete = jest.fn()
  const baseCellProps = {
    onExecute: mockOnExecute,
    onUpdate: mockOnUpdate,
    onDelete: mockOnDelete,
    isExecuting: false,
  }

  const createCell = (type: CellType, overrides = {}): Cell => ({
    id: `cell-${type}`,
    notebook_id: 'notebook-1',
    type,
    content: `Content for ${type}`,
    status: 'idle',
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    ...overrides,
  })

  afterEach(() => {
    jest.clearAllMocks()
  })

  it('renders MarkdownCell for "markdown" type', () => {
    const cell = createCell('markdown')
    render(<CellFactory cell={cell} {...baseCellProps} />)
    expect(screen.getByTestId('markdown-cell')).toBeInTheDocument();
    const receivedProps = (MarkdownCellMock as unknown as jest.Mock).mock.calls[0][0];
    expect(receivedProps.cell).toEqual(cell);
    expect(receivedProps.onUpdate).toBe(mockOnUpdate);
    expect(receivedProps.onDelete).toBe(mockOnDelete);
  })

  it('renders ToolCell for "tool" type', () => {
    const cell = createCell('tool')
    render(<CellFactory cell={cell} {...baseCellProps} />)
    expect(screen.getByTestId('tool-cell')).toBeInTheDocument();
    const receivedProps = (ToolCellMock as unknown as jest.Mock).mock.calls[0][0];
    expect(receivedProps.cell).toEqual(cell);
    expect(receivedProps.onExecute).toBe(mockOnExecute);
    expect(receivedProps.onUpdate).toBe(mockOnUpdate);
    expect(receivedProps.onDelete).toBe(mockOnDelete);
    expect(receivedProps.isExecuting).toBe(false);
  })

  it('renders ToolCell for legacy "github" type', () => {
    const cell = createCell('github')
    render(<CellFactory cell={cell} {...baseCellProps} />)
    expect(screen.getByTestId('tool-cell')).toBeInTheDocument();
    const receivedProps = (ToolCellMock as unknown as jest.Mock).mock.calls[0][0];
    expect(receivedProps.cell).toEqual(cell);
    expect(receivedProps.onExecute).toBe(mockOnExecute);
    expect(receivedProps.onUpdate).toBe(mockOnUpdate);
    expect(receivedProps.onDelete).toBe(mockOnDelete);
    expect(receivedProps.isExecuting).toBe(false);
  })

  it('renders ToolCell for legacy "python" type', () => {
    const cell = createCell('python')
    render(<CellFactory cell={cell} {...baseCellProps} />)
    expect(screen.getByTestId('tool-cell')).toBeInTheDocument();
    const receivedProps = (ToolCellMock as unknown as jest.Mock).mock.calls[0][0];
    expect(receivedProps.cell).toEqual(cell);
    expect(receivedProps.onExecute).toBe(mockOnExecute);
    expect(receivedProps.onUpdate).toBe(mockOnUpdate);
    expect(receivedProps.onDelete).toBe(mockOnDelete);
    expect(receivedProps.isExecuting).toBe(false);
  })

  it('renders ToolCell for any unknown type (mapped to tool)', () => {
    // Cast to any to bypass type checking for this specific test case
    const cell = createCell('unknown_type' as CellType)
    render(<CellFactory cell={cell} {...baseCellProps} />)
    // Unknown types are mapped to tool cells
    expect(screen.getByTestId('tool-cell')).toBeInTheDocument();
    const receivedProps = (ToolCellMock as unknown as jest.Mock).mock.calls[0][0];
    expect(receivedProps.cell).toEqual(cell);
  })
})
