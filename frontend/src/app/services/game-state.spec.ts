import { TestBed } from '@angular/core/testing';

import { GameStateService } from './game-state';

describe('GameStateService', () => {
  let service: GameStateService;

  beforeEach(() => {
    TestBed.configureTestingModule({});
    service = TestBed.inject(GameStateService);
  });

  it('starts from the initial position with legal white moves', () => {
    const state = service.snapshot();

    expect(state.moves).toEqual([]);
    expect(state.turn).toBe('white');
    expect(state.legalDests.get('e2')).toContain('e4');
  });

  it('accepts a legal move and updates analysis payload fields', () => {
    const result = service.applyMove({ from: 'e2', to: 'e4' });

    expect(result.ok).toBe(true);
    expect(result.snapshot.moves).toEqual(['e2e4']);
    expect(result.snapshot.pgn).toBe('1. e4');
    expect(result.snapshot.fen).toBe(
      'rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1',
    );
    expect(result.snapshot.turn).toBe('black');
    expect(result.snapshot.legalDests.get('e7')).toContain('e5');
  });

  it('rejects an illegal move and keeps the current position', () => {
    const before = service.snapshot();
    const result = service.applyMove({ from: 'e2', to: 'e5' });

    expect(result.ok).toBe(false);
    expect(result.snapshot.fen).toBe(before.fen);
    expect(result.snapshot.moves).toEqual([]);
  });

  it('resets the game after moves', () => {
    service.applyMove({ from: 'e2', to: 'e4' });

    const reset = service.reset();

    expect(reset.moves).toEqual([]);
    expect(reset.turn).toBe('white');
    expect(reset.legalDests.get('g1')).toContain('f3');
  });
});
