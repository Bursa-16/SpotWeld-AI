def analysis_input():
    return {
        "material_family": "Düşük / Orta Karbonlu Çelik",
        "material_subtype": "Düşük karbonlu çelik",
        "stack_count": "2T",
        "layers": [
            {"material_family":"Düşük / Orta Karbonlu Çelik","material_subtype":"Düşük karbonlu çelik","thickness_mm":1.0,"coated":False},
            {"material_family":"Düşük / Orta Karbonlu Çelik","material_subtype":"Düşük karbonlu çelik","thickness_mm":1.0,"coated":False},
        ],
        "current_ka": 8.0, "weld_cycles": 12, "force_kn": 3.0,
        "tip_diameter_mm": 6.0, "squeeze_cycles": 15, "hold_cycles": 15,
        "cooling_flow_lpm": 6.0, "cooling_temp_c": 20,
        "dc_current": True, "adhesive": False, "shunt_risk": False,
    }


def test_project_weld_point_revision_and_approval(client, auth_headers):
    project = client.post('/api/v1/projects', headers=auth_headers, json={
        'project_code':'P-001','project_name':'Test Project','customer':'OEM'
    })
    assert project.status_code == 201
    project_id = project.json()['id']

    point = client.post(f'/api/v1/projects/{project_id}/weld-points', headers=auth_headers, json={
        'point_code':'W001','part_no':'PN-1','criticality':'Yapısal',
        'analysis_input': analysis_input()
    })
    assert point.status_code == 201
    body = point.json()
    assert body['analysis_result']['selected_model'] == 'OEM Referans Tablosu'
    point_id = body['id']

    updated_input = analysis_input(); updated_input['current_ka'] = 8.5
    updated = client.patch(f'/api/v1/weld-points/{point_id}', headers=auth_headers, json={
        'changed_by':'Engineer','change_reason':'Current optimization',
        'analysis_input': updated_input
    })
    assert updated.status_code == 200
    assert updated.json()['version_no'] == 2

    revisions = client.get(f'/api/v1/weld-points/{point_id}/revisions', headers=auth_headers)
    assert revisions.status_code == 200
    assert len(revisions.json()) == 1

    approval = client.post(f'/api/v1/weld-points/{point_id}/approvals', headers=auth_headers, json={
        'approval_type':'Proses Onayı','approver':'Lead Engineer','status':'Onaylandı','note':'Validated'
    })
    assert approval.status_code == 201

    detail = client.get(f'/api/v1/weld-points/{point_id}', headers=auth_headers)
    assert detail.json()['approval_status'] == 'Onaylandı'
