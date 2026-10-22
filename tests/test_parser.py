from bot.scanner.transaction_parser import find_initialized_mints, find_fee_payer, find_raydium_launch, RAYDIUM_LAUNCHPAD_PROGRAM_ID

def test_parser():
    tx = {
        "transaction": {
            "message": {
                "accountKeys": [
                    {"pubkey": "DEPLOYER_TEST", "signer": True, "writable": True}
                ],
                "instructions": [
                    {
                        "program": "spl-token",
                        "programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
                        "parsed": {
                            "type": "initializeMint2",
                            "info": {"mint": "MINT_TEST"}
                        }
                    }
                ]
            }
        },
        "meta": {"innerInstructions": []}
    }
    assert find_initialized_mints(tx) == ["MINT_TEST"]
    assert find_fee_payer(tx) == "DEPLOYER_TEST"
    launch_ix = {"programId": RAYDIUM_LAUNCHPAD_PROGRAM_ID,
                 "accounts": ["payer", "creator", "a", "b", "c", "pool", "MINT_TEST"]}
    tx["transaction"]["message"]["instructions"].append(launch_ix)
    assert find_raydium_launch(tx) is None  # Instruction fictive sans initialisation valide
    tx["transaction"]["message"]["instructions"].pop(0)
    assert find_raydium_launch(tx) is None  # Même instruction dans un swap : aucun lancement.
    print("Tests OK")

if __name__ == "__main__":
    test_parser()
