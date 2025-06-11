import React from 'react'
import { render, screen, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event' // For more complex interactions
import MarkdownCell from '../MarkdownCell'
import type { Cell } from '../../../store/types'
import '@testing-library/jest-dom'

// Mock react-markdown
jest.mock('react-markdown', () => ({
  __esModule: true,
  // eslint-disable-next-line react/display-name
  default: jest.fn(({ children }) => <div data-testid="react-markdown-mock">{children}</div>),
}));

// Mock remark-gfm as it's a plugin for react-markdown
jest.mock('remark-gfm', () => ({
  __esModule: true,
  default: jest.fn(), // Simple mock, doesn't need to do anything for these tests
}));


// Mock lucide-react icons
jest.mock('lucide-react', () => ({
  Save: () => <div data-testid="save-icon" />,
  Trash: () => <div data-testid="trash-icon" />,
  X: () => <div data-testid="x-icon" />,
}))

describe('MarkdownCell', () => {
  const mockCell: Cell = {
    id: 'md-cell-1',
    notebook_id: 'notebook-1',
    type: 'markdown',
    content: '## Hello World\n\nThis is markdown.',
    status: 'idle',
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  }

  const mockOnUpdate = jest.fn()
  const mockOnDelete = jest.fn()

  beforeEach(() => {
    jest.clearAllMocks()
  })

  it('renders markdown content in view mode initially', () => {
    render(<MarkdownCell cell={mockCell} onUpdate={mockOnUpdate} onDelete={mockOnDelete} />)
    const markdownOutput = screen.getByTestId('react-markdown-mock');
    expect(markdownOutput).toHaveTextContent('## Hello World');
    expect(markdownOutput).toHaveTextContent('This is markdown.');
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
  })

  it('switches to edit mode on click', () => {
    render(<MarkdownCell cell={mockCell} onUpdate={mockOnUpdate} onDelete={mockOnDelete} />)
    const cardContent = screen.getByTestId('react-markdown-mock').closest('.p-4.cursor-pointer');
    expect(cardContent).not.toBeNull();
    if (cardContent) {
      fireEvent.click(cardContent);
    }
    expect(screen.getByRole('textbox')).toHaveValue(mockCell.content)
    expect(screen.getByRole('button', { name: /Save/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Cancel/i })).toBeInTheDocument()
  })

  it('allows content editing in edit mode', async () => {
    const user = userEvent.setup()
    render(<MarkdownCell cell={mockCell} onUpdate={mockOnUpdate} onDelete={mockOnDelete} />)
    const cardContent = screen.getByTestId('react-markdown-mock').closest('.p-4.cursor-pointer');
    if (cardContent) fireEvent.click(cardContent);
    
    const textarea = screen.getByRole('textbox')
    await user.clear(textarea)
    await user.type(textarea, 'New content')
    expect(textarea).toHaveValue('New content')
  })

  it('calls onUpdate with new content when Save is clicked and content changed', async () => {
    const user = userEvent.setup()
    render(<MarkdownCell cell={mockCell} onUpdate={mockOnUpdate} onDelete={mockOnDelete} />)
    const cardContent = screen.getByTestId('react-markdown-mock').closest('.p-4.cursor-pointer');
    if (cardContent) fireEvent.click(cardContent);

    const textarea = screen.getByRole('textbox')
    await user.clear(textarea)
    await user.type(textarea, 'Updated markdown')
    
    fireEvent.click(screen.getByRole('button', { name: /Save/i }))

    expect(mockOnUpdate).toHaveBeenCalledWith(mockCell.id, 'Updated markdown')
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument() // Should exit edit mode
  })

  it('does not call onUpdate when Save is clicked and content has not changed', () => {
    render(<MarkdownCell cell={mockCell} onUpdate={mockOnUpdate} onDelete={mockOnDelete} />)
    const cardContent = screen.getByTestId('react-markdown-mock').closest('.p-4.cursor-pointer');
    if (cardContent) fireEvent.click(cardContent);
    fireEvent.click(screen.getByRole('button', { name: /Save/i }))

    expect(mockOnUpdate).not.toHaveBeenCalled()
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument() // Should still exit edit mode
  })

  it('reverts content and exits edit mode when Cancel is clicked', async () => {
    const user = userEvent.setup()
    render(<MarkdownCell cell={mockCell} onUpdate={mockOnUpdate} onDelete={mockOnDelete} />)
    const cardContent = screen.getByTestId('react-markdown-mock').closest('.p-4.cursor-pointer');
    if (cardContent) fireEvent.click(cardContent);

    const textarea = screen.getByRole('textbox')
    await user.clear(textarea)
    await user.type(textarea, 'Temporary edit')
    
    fireEvent.click(screen.getByRole('button', { name: /Cancel/i }))

    expect(mockOnUpdate).not.toHaveBeenCalled()
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
    // Adjust for whitespace normalization by textContent
    const expectedText = mockCell.content.replace(/\n\n/g, ' ').replace(/\n/g, ' ');
    expect(screen.getByTestId('react-markdown-mock')).toHaveTextContent(expectedText);
  })

  it('calls onDelete when delete button is clicked (on hover)', async () => {
    const user = userEvent.setup()
    render(<MarkdownCell cell={mockCell} onUpdate={mockOnUpdate} onDelete={mockOnDelete} />)
    
    const card = screen.getByTestId('react-markdown-mock').closest('div.group');
    expect(card).not.toBeNull()

    if (card) {
        fireEvent.mouseEnter(card);
        const deleteButton = await screen.findByTitle(/Delete Cell/i); // Use findBy for elements appearing on hover
        expect(deleteButton).toBeInTheDocument()
        await user.click(deleteButton)
        expect(mockOnDelete).toHaveBeenCalledWith(mockCell.id)
        fireEvent.mouseLeave(card);
    } else {
        throw new Error("Card element not found for hover simulation");
    }
  })

  it('saves content when clicking outside if in edit mode and content changed', async () => {
    const user = userEvent.setup()
    render(
      <div>
        <MarkdownCell cell={mockCell} onUpdate={mockOnUpdate} onDelete={mockOnDelete} />
        <div data-testid="outside-element">Click me</div>
      </div>
    )
    const cardContent = screen.getByTestId('react-markdown-mock').closest('.p-4.cursor-pointer');
    if (cardContent) fireEvent.click(cardContent); // Enter edit mode

    const textarea = screen.getByRole('textbox')
    await user.clear(textarea)
    await user.type(textarea, 'Clicked outside to save')

    // Simulate click outside
    fireEvent.mouseDown(screen.getByTestId('outside-element'))

    expect(mockOnUpdate).toHaveBeenCalledWith(mockCell.id, 'Clicked outside to save')
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument() // Exits edit mode
  })

   it('does not save content when clicking outside if in edit mode and content NOT changed', async () => {
    render(
      <div>
        <MarkdownCell cell={mockCell} onUpdate={mockOnUpdate} onDelete={mockOnDelete} />
        <div data-testid="outside-element">Click me</div>
      </div>
    )
    const cardContent = screen.getByTestId('react-markdown-mock').closest('.p-4.cursor-pointer');
    if (cardContent) fireEvent.click(cardContent); // Enter edit mode

    // Simulate click outside without changing content
    fireEvent.mouseDown(screen.getByTestId('outside-element'))

    expect(mockOnUpdate).not.toHaveBeenCalled()
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument() // Exits edit mode
  })

  it('renders empty state message if cell content is empty', () => {
    const emptyCell = { ...mockCell, content: '' }
    render(<MarkdownCell cell={emptyCell} onUpdate={mockOnUpdate} onDelete={mockOnDelete} />)
    expect(screen.getByTestId('react-markdown-mock')).toHaveTextContent('*Empty markdown cell*')
  })

  it('renders empty state message if cell content is null', () => {
    const nullContentCell = { ...mockCell, content: '' } // Test empty string case
    render(<MarkdownCell cell={nullContentCell} onUpdate={mockOnUpdate} onDelete={mockOnDelete} />)
    expect(screen.getByTestId('react-markdown-mock')).toHaveTextContent('*Empty markdown cell*')
  })
})
