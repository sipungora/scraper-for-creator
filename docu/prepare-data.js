// Этот узел будет идти после узла "Split Text"
// Предположим, что данные приходят с полем `text` (сам чанк) 
// и полем `source_url` и `topic` из предыдущих шагов.

const chunks = $input.all();
const itemsToUpsert = [];

for (const chunk of chunks) {
  itemsToUpsert.push({
    // 'content' - это колонка в Supabase, куда мы кладем сам текст
    content: chunk.json.text,
    
    // 'metadata' - это колонка, в которую мы кладем JSON объект
    metadata: {
      url: chunk.json.source_url, // URL статьи, из которой взят чанк
      topic: chunk.json.topic      // Тема, к которой мы отнесли этот URL
    }
  });
}

return itemsToUpsert;