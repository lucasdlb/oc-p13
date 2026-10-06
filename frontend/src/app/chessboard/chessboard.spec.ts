import { TestBed } from '@angular/core/testing';

const chessground = vi.hoisted(() => ({
  api: {
    set: vi.fn(),
    setShapes: vi.fn(),
    destroy: vi.fn(),
  },
}));

vi.mock('@lichess-org/chessground', () => ({
  Chessground: vi.fn(() => chessground.api),
}));

import { ChessboardComponent } from './chessboard';

describe('ChessboardComponent', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('updates the preview arrow when its input changes after board creation', async () => {
    const fixture = TestBed.createComponent(ChessboardComponent);
    fixture.componentRef.setInput('fen', '8/8/8/8/8/8/8/8 w - - 0 1');
    fixture.componentRef.setInput('dests', new Map());
    fixture.detectChanges();
    await fixture.whenStable();
    chessground.api.setShapes.mockClear();

    fixture.componentRef.setInput('arrow', { from: 'e7', to: 'e5' });
    fixture.detectChanges();
    await fixture.whenStable();

    expect(chessground.api.setShapes).toHaveBeenLastCalledWith([
      { orig: 'e7', dest: 'e5', brush: 'green' },
    ]);
  });
});
