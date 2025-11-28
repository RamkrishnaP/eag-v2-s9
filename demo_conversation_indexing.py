#!/usr/bin/env python3
"""
Demo script for the Smart Conversation Indexing System
Shows how past conversations are indexed and retrieved
"""

import sys

from modules.conversation_indexer_simple import ConversationIndexer


def print_header(text):
    print("\n" + "=" * 80)
    print(f"  {text}")
    print("=" * 80 + "\n")


def main():
    print_header("🧠 Smart Conversation Indexing System - Demo")

    # Initialize indexer
    print("📥 Initializing conversation indexer...")
    indexer = ConversationIndexer()

    # Index conversations
    print("\n📚 Indexing past conversations...")
    indexer.index_conversations()

    # Show statistics
    print_header("📊 Indexing Statistics")
    stats = indexer.get_statistics()
    print(f"  Total conversations indexed: {stats['total_conversations']}")
    print(f"  Successful conversations: {stats['successful_conversations']}")
    print(f"  Success rate: {stats['success_rate']:.1%}")
    print(f"  Indexed files: {stats['indexed_files']}")

    if stats.get("most_used_tools"):
        print("\n  Most used tools:")
        for tool, count in stats["most_used_tools"]:
            print(f"    - {tool}: {count} times")

    # Test search functionality
    if stats["total_conversations"] > 0:
        print_header("🔍 Search Demo")

        # Show example queries from past conversations
        print("Example past queries:")
        for i, convo in enumerate(indexer.metadata[:3], 1):
            print(f"  {i}. {convo['initial_query']}")

        # Interactive search
        print("\n" + "-" * 80)
        print("Now you can search for relevant past conversations!")
        print("Try queries like:")
        print("  - 'payment information'")
        print("  - 'apartment details'")
        print("  - Similar to your past queries")
        print("-" * 80)

        while True:
            try:
                query = input("\n🔍 Enter search query (or 'quit' to exit): ").strip()

                if query.lower() in ["quit", "exit", "q"]:
                    break

                if not query:
                    continue

                print(f"\nSearching for: '{query}'")
                print("-" * 80)

                # Get relevant context
                context = indexer.get_relevant_context(query, top_k=3)

                if context:
                    print(context)
                else:
                    print("No relevant conversations found.")

                # Show raw results
                results = indexer.search_conversations(query, top_k=3)
                if results:
                    print("\n📈 Similarity Scores:")
                    for i, result in enumerate(results, 1):
                        print(
                            f"  {i}. {result['similarity_score']:.2%} - {result['initial_query'][:60]}..."
                        )

            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"Error: {e}")
                continue

    else:
        print("\n⚠️  No conversations found to search.")
        print("Run the agent with some queries first to build up conversation history.")

    print_header("✅ Demo Complete")
    print("The conversation indexing system is ready to enhance your agent!")
    print("\nKey features:")
    print("  ✓ Automatic indexing of all conversations")
    print("  ✓ Semantic similarity search")
    print("  ✓ Incremental updates (only indexes new conversations)")
    print("  ✓ Integrated into agent planning phase")
    print("\nSee CONVERSATION_INDEXING_README.md for full documentation.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n👋 Goodbye!")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
