from .wire import MUPFailure

TOOLS=[
 {'name':'maltose_show','description':'Create or replace your local surface, preserving its window and selection when stable node IDs remain. document format: {root:{node_id:"content",type:"text",props:{text:"Hello"}}}. Allowed types: stack, text, button (label/action_id), table (columns:[string],rows:[[values]]), chart.line (points:[[x,y]]), canvas (width,height,children), canvas.rect/ellipse/triangle/text (bounded x,y,width,height and optional hex color/label). Canvas elements are fixed safe vector shapes; never send HTML, SVG markup, JavaScript or code. stack uses children:[nodes]. Buttons require document.actions:[action_id].','parameters':{'type':'object','properties':{'surface_id':{'type':'string'},'title':{'type':'string'},'document':{'type':'object'}},'required':['surface_id','title','document'],'additionalProperties':False}},
 {'name':'maltose_patch','description':'Atomically update your surface using expected_revision and typed set_props/insert_node/remove_node/move_node operations.','parameters':{'type':'object','properties':{'surface_id':{'type':'string'},'expected_revision':{'type':'integer'},'operations':{'type':'array','items':{'type':'object'}}},'required':['surface_id','expected_revision','operations'],'additionalProperties':False}},
 {'name':'maltose_context','description':'Get current authorized focus, selected node/interval and viewport. Call before referring to this chart or the selected range.','parameters':{'type':'object','properties':{'surface_id':{'type':'string'}},'additionalProperties':False}},
 {'name':'maltose_resolve','description':'Get ranked fresh reference candidates with evidence. If requires_clarification is true, ask the user; do not guess.','parameters':{'type':'object','properties':{'phrase':{'type':'string'},'surface_id':{'type':'string'},'node_id':{'type':'string'}},'required':['phrase'],'additionalProperties':False}},
 {'name':'maltose_detach','description':'Move your existing surface into a native window while preserving selected nodes and zoom.','parameters':{'type':'object','properties':{'surface_id':{'type':'string'}},'required':['surface_id'],'additionalProperties':False}},
 {'name':'maltose_attach','description':'Return your detached surface to Workspace.','parameters':{'type':'object','properties':{'surface_id':{'type':'string'}},'required':['surface_id'],'additionalProperties':False}},
]
COMMANDS={'maltose_show':'surface.create','maltose_patch':'ui.patch','maltose_context':'ui.context.get','maltose_resolve':'ui.context.resolve_reference','maltose_detach':'surface.detach','maltose_attach':'surface.attach'}

def show_surface(wire, payload):
    """Create an owned surface when get() says it is absent or private.

    Host intentionally returns the same forbidden response for an unknown surface
    and a surface owned by another Agent.  surface.create remains the authority:
    it creates a missing ID and safely rejects a collision without exposing or
    overwriting another Agent's surface.
    """
    try:
        existing = wire.request('surface.get', {'surface_id': payload['surface_id']})
    except MUPFailure as error:
        if error.code not in ('forbidden', 'unavailable'):
            raise
        return wire.request('surface.create', payload)
    return wire.request('ui.render', {
        'surface_id': payload['surface_id'],
        'expected_revision': existing['revision'],
        'document': payload['document'],
    })
