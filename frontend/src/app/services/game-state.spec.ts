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
    expect(state.line).toEqual([]);
    expect(state.currentIndex).toBe(0);
    expect(state.totalMoves).toBe(0);
    expect(state.canGoBack).toBe(false);
    expect(state.canGoForward).toBe(false);
    expect(state.turn).toBe('white');
    expect(state.legalDests.get('e2')).toContain('e4');
  });

  it('accepts a legal move and updates analysis payload fields', () => {
    const result = service.applyMove({ from: 'e2', to: 'e4' });

    expect(result.ok).toBe(true);
    expect(result.snapshot.moves).toEqual(['e2e4']);
    expect(result.snapshot.line).toEqual(['e2e4']);
    expect(result.snapshot.pgn).toBe('1. e4');
    expect(result.snapshot.fen).toBe(
      'rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1',
    );
    expect(result.snapshot.turn).toBe('black');
    expect(result.snapshot.currentIndex).toBe(1);
    expect(result.snapshot.totalMoves).toBe(1);
    expect(result.snapshot.canGoBack).toBe(true);
    expect(result.snapshot.canGoForward).toBe(false);
    expect(result.snapshot.legalDests.get('e7')).toContain('e5');
  });

  it('rejects an illegal move and keeps the current position', () => {
    const before = service.snapshot();
    const result = service.applyMove({ from: 'e2', to: 'e5' });

    expect(result.ok).toBe(false);
    expect(result.snapshot.fen).toBe(before.fen);
    expect(result.snapshot.moves).toEqual([]);
    expect(result.snapshot.currentIndex).toBe(0);
  });

  it('resets the game after moves', () => {
    service.applyMove({ from: 'e2', to: 'e4' });

    const reset = service.reset();

    expect(reset.moves).toEqual([]);
    expect(reset.line).toEqual([]);
    expect(reset.currentIndex).toBe(0);
    expect(reset.totalMoves).toBe(0);
    expect(reset.turn).toBe('white');
    expect(reset.legalDests.get('g1')).toContain('f3');
  });

  it('navigates backward and forward through the timeline', () => {
    service.applyMove({ from: 'e2', to: 'e4' });
    service.applyMove({ from: 'e7', to: 'e5' });

    const back = service.goBack();

    expect(back).not.toBeNull();
    expect(back!.currentIndex).toBe(1);
    expect(back!.totalMoves).toBe(2);
    expect(back!.moves).toEqual(['e2e4']);
    expect(back!.fen).toBe('rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1');
    expect(back!.pgn).toBe('1. e4');
    expect(back!.turn).toBe('black');
    expect(back!.legalDests.get('e7')).toContain('e5');

    const start = service.goBack();

    expect(start!.currentIndex).toBe(0);
    expect(start!.moves).toEqual([]);
    expect(start!.canGoBack).toBe(false);

    expect(service.goBack()).toBeNull();

    const forward = service.goForward();

    expect(forward!.currentIndex).toBe(1);
    expect(forward!.moves).toEqual(['e2e4']);

    const last = service.goForward();

    expect(last!.currentIndex).toBe(2);
    expect(last!.moves).toEqual(['e2e4', 'e7e5']);
    expect(last!.canGoForward).toBe(false);
    expect(last!.fen).toBe('rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2');

    expect(service.goForward()).toBeNull();
  });

  it('discards the future variation when playing a new move after going back', () => {
    service.applyMove({ from: 'e2', to: 'e4' });
    service.applyMove({ from: 'e7', to: 'e5' });
    service.goBack();

    const result = service.applyMove({ from: 'd7', to: 'd5' });

    expect(result.ok).toBe(true);
    expect(result.snapshot.line).toEqual(['e2e4', 'd7d5']);
    expect(result.snapshot.moves).toEqual(['e2e4', 'd7d5']);
    expect(result.snapshot.currentIndex).toBe(2);
    expect(result.snapshot.totalMoves).toBe(2);
    expect(result.snapshot.canGoForward).toBe(false);
    expect(result.snapshot.fen).toBe(
      'rnbqkbnr/ppp1pppp/8/3p4/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2',
    );
  });

  it('keeps the line when replaying the same move after going back', () => {
    service.applyMove({ from: 'e2', to: 'e4' });
    service.applyMove({ from: 'e7', to: 'e5' });
    service.goBack();

    const result = service.applyMove({ from: 'e7', to: 'e5' });

    expect(result.ok).toBe(true);
    expect(result.snapshot.line).toEqual(['e2e4', 'e7e5']);
    expect(result.snapshot.totalMoves).toBe(2);
    expect(result.snapshot.canGoForward).toBe(false);
  });

  it('keeps the discarded variation out of navigation after a branch', () => {
    service.applyMove({ from: 'e2', to: 'e4' });
    service.applyMove({ from: 'e7', to: 'e5' });
    service.goBack();
    service.applyMove({ from: 'd7', to: 'd5' });

    expect(service.goForward()).toBeNull();
    expect(service.goBack()!.moves).toEqual(['e2e4']);
  });
});
