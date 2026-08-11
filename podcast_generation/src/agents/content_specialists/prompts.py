class BookSelectionPrompt:

    FIND_BOOKS_PROMPT = """
    For this step in the workflow, your goal is to find books that are
    either popular or could be considered as hidden gems because, although not
    many people know about this, it contains world-class advices/tips that
    would greatly contribute to the listeners self-development.

    Find such that are not yet listed in the wishlist or finished section of the
    booklist, so make sure they are knew. After that update the booklist.
    """

class ContentDirectorPrompt:
    
    REVIEW_EXPERT_PROFILE="""
    For this step, analyse the expert profile that has been created according to
    the criteria mentioned above. 
    If it is ready to pass, use your call_script_drafter_agent tool to send to the next agent.
    If it is not ready yet, send it back to the Expert Personal creator agent to refine it
    with call_expert_builder_agent.
    """