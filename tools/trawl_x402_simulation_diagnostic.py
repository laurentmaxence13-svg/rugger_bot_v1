"""Trawl x402 Solana: READ-ONLY simulation. No wallet key loaded. No payment sent."""
import base64,json,urllib.request,urllib.error
from solders.hash import Hash
from solders.instruction import AccountMeta,Instruction
from solders.message import MessageV0
from solders.pubkey import Pubkey
from solders.signature import Signature
from solders.transaction import VersionedTransaction
from spl.token.instructions import get_associated_token_address

URL="https://trawl.run/scan"
RPC="https://api.mainnet-beta.solana.com"
ORDER={"preset":"raydium-launchpad","start_epoch":1064,"end_epoch":1068}
WALLET="HGvjj5qkKTy6hNZxftt1okWKKjwuxgxFH2EEQRPVCWib"
TRAWL="Eo6S17vzoEaAs4gTMBuhWchJ1sxrQ2c7hS3K1JxcTrjy"
USDC="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
TOKEN="TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
MEMO="MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr"
AMOUNT=4030000

def post(url,body):
    request=urllib.request.Request(url,data=json.dumps(body).encode(),
        headers={"Content-Type":"application/json"},method="POST")
    try:
        with urllib.request.urlopen(request,timeout=25) as response:
            return response.status,json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code,json.loads(error.read())

def rpc(method,params):
    status,body=post(RPC,{"jsonrpc":"2.0","id":1,"method":method,"params":params})
    if status!=200 or body.get("error"):
        raise RuntimeError(f"RPC {method}: {str(body.get('error',body))[:250]}")
    return body["result"]

def main():
    print("DIAGNOSTIC TRAWL - AUCUNE CLE PRIVEE / AUCUN PAIEMENT")
    status,quote=post(URL,ORDER)
    if status!=402:raise RuntimeError(f"Devis Trawl inattendu HTTP {status}")
    requirements=quote.get("accepts",[])
    if len(requirements)!=1:raise RuntimeError("Devis ambigu")
    req=requirements[0]
    expected={"scheme":"exact","network":"solana","asset":USDC,
              "payTo":TRAWL,"maxAmountRequired":str(AMOUNT)}
    for field,value in expected.items():
        if req.get(field)!=value:raise RuntimeError("Devis modifie: "+field)
    if quote.get("quote",{}).get("priceAtomic")!=str(AMOUNT):
        raise RuntimeError("Prix different de 4.03 USDC")
    sponsor=req.get("extra",{}).get("feePayer")
    if not sponsor:raise RuntimeError("Sponsor des frais absent")
    source=get_associated_token_address(Pubkey.from_string(WALLET),Pubkey.from_string(USDC))
    target=get_associated_token_address(Pubkey.from_string(TRAWL),Pubkey.from_string(USDC))
    print("PRIX : 4.03 USDC, simulation seulement")
    print("SPONSOR :",sponsor)
    print("SOURCE ATA :",source)
    print("DESTINATION ATA :",target)
    for name,address in [("WALLET",WALLET),("SOURCE USDC",str(source)),
                         ("DESTINATION USDC",str(target)),("SPONSOR",sponsor)]:
        info=rpc("getAccountInfo",[address,{"encoding":"base64"}])
        print(name,":","EXISTE" if info["value"] is not None else "ABSENT")
    balance=rpc("getTokenAccountBalance",[str(source)])
    print("SOURCE USDC :",balance["value"]["uiAmountString"])
    print("SOL SPONSOR, lamports :",rpc("getBalance",[sponsor])["value"])
    latest=rpc("getLatestBlockhash",[{"commitment":"processed"}])
    blockhash=Hash.from_string(latest["value"]["blockhash"])
    transfer=Instruction(Pubkey.from_string(TOKEN),[
        AccountMeta(source,False,True),
        AccountMeta(Pubkey.from_string(USDC),False,False),
        AccountMeta(target,False,True),
        AccountMeta(Pubkey.from_string(WALLET),True,False)
    ],bytes([12])+AMOUNT.to_bytes(8,"little")+bytes([6]))
    memo=Instruction(Pubkey.from_string(MEMO),[],b"rugger-readonly-test")
    message=MessageV0.try_compile(Pubkey.from_string(sponsor),[transfer,memo],[],blockhash)
    signatures=[Signature.default()]*message.header.num_required_signatures
    tx=VersionedTransaction.populate(message,signatures)
    encoded=base64.b64encode(bytes(tx)).decode("ascii")
    simulation=rpc("simulateTransaction",[encoded,{
        "encoding":"base64","sigVerify":False,"replaceRecentBlockhash":True,
        "commitment":"processed"}])
    value=simulation["value"]
    print("SIMULATION RESULTAT :",json.dumps(value.get("err")))
    print("UNITES :",value.get("unitsConsumed"))
    for line in (value.get("logs") or [])[-18:]:
        print("LOG :",line[:300])
    print("AUCUNE TRANSACTION ENVOYEE / AUCUN USDC DEPENSE")

if __name__=="__main__":
    try:main()
    except Exception as exc:
        print("DIAGNOSTIC ERREUR :",type(exc).__name__,str(exc)[:250])
        print("AUCUNE TRANSACTION ENVOYEE PAR CE SCRIPT")
