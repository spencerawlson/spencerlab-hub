"""Browser entry point for pygbag (WebAssembly).

The game itself is unchanged: this only drives ATMGame's own handle/update/draw from an
async loop, because the browser needs control back every frame (await asyncio.sleep(0)).
Balances live in the page's in-memory filesystem, so they reset on reload.
"""
import asyncio

import pygame

import atm_game


async def main():
    pygame.init()
    game = atm_game.ATMGame()
    while game.running:
        dt = game.clock.tick(atm_game.FPS) / 1000.0
        for event in pygame.event.get():
            game.handle(event)
        game.update(dt)
        game.draw()
        await asyncio.sleep(0)


asyncio.run(main())
