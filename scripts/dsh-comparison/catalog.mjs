// Catalog discovery hosted by the ordinary DSH profile launcher; no model calls.
import { writeFile } from 'node:fs/promises';

export const name = 'comparison-catalog';
export const inject = ['llm', 'loader'];

export function apply(ctx) {
  void (async () => {
    await ctx.get('loader').await();
    const llm = ctx.get('llm');
    const providers = await Promise.all(llm.listProviders().map(async ({ id }) => ({
      id,
      models: await Promise.all((await llm.listModels(id)).map(async model => {
        const { name, reasoning } = await llm.resolveModelInfo(id, model.id);
        return { id: model.id, name, reasoning };
      })),
    })));
    await writeFile(process.env.DSH_COMPARISON_CATALOG, JSON.stringify(providers, null, 2));
    ctx.get('appExit')(0);
  })().catch(error => {
    console.error(error.message);
    ctx.get('appExit')(1);
  });
}
